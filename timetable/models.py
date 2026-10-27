from datetime import time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

# Weeks run Saturday -> Thursday. Day index 0 is Saturday.
DAY_CHOICES = [
    (0, 'Saturday'),
    (1, 'Sunday'),
    (2, 'Monday'),
    (3, 'Tuesday'),
    (4, 'Wednesday'),
    (5, 'Thursday'),
]
DAY_SHORT = ['Sat', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu']

DEFAULT_TIMESLOTS = [
    (time(8, 0), time(9, 30)),
    (time(9, 40), time(11, 10)),
    (time(11, 20), time(12, 50)),
    (time(13, 0), time(14, 30)),
    (time(14, 40), time(16, 10)),
    (time(16, 20), time(17, 50)),
]


class Space(models.Model):
    """One section of one major, e.g. '2nd year MCIL.SD, Section B'."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    major = models.CharField(max_length=60, blank=True)
    section = models.CharField(max_length=30, blank=True)
    year = models.CharField(max_length=30, blank=True, help_text='e.g. "2nd year"')
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('public:space', args=[self.slug])

    def create_default_timeslots(self):
        if not self.timeslots.exists():
            TimeSlot.objects.bulk_create(
                TimeSlot(space=self, start=s, end=e, order=i)
                for i, (s, e) in enumerate(DEFAULT_TIMESLOTS)
            )


class SpaceMembership(models.Model):
    """Grants a user admin rights over one space. Superusers manage everything."""

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='space_memberships')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['space', 'user'], name='unique_space_member')]

    def __str__(self):
        return f'{self.user} @ {self.space}'


class Group(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='groups')
    name = models.CharField(max_length=20)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        constraints = [models.UniqueConstraint(fields=['space', 'name'], name='unique_group_name')]

    def __str__(self):
        return self.name


class TimeSlot(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='timeslots')
    start = models.TimeField()
    end = models.TimeField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['start']

    def __str__(self):
        return f'{self.start:%H:%M}–{self.end:%H:%M}'

    def clean(self):
        if self.start and self.end and self.end <= self.start:
            raise ValidationError('End time must be after start time.')


class Subject(models.Model):
    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='subjects')
    name = models.CharField(max_length=80)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['space', 'name'], name='unique_subject_name')]

    def __str__(self):
        return self.name


class Week(models.Model):
    DRAFT = 'draft'
    PUBLISHED = 'published'
    STATUS_CHOICES = [(DRAFT, 'Draft'), (PUBLISHED, 'Published')]

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='weeks')
    start = models.DateField(help_text='The Saturday that starts the week.')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    copied_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start']
        constraints = [models.UniqueConstraint(fields=['space', 'start'], name='unique_space_week')]

    def __str__(self):
        return f'{self.space} — week of {self.start:%d %b %Y}'

    def clean(self):
        if self.start and self.start.weekday() != 5:
            raise ValidationError('A week must start on a Saturday.')

    @property
    def is_published(self):
        return self.status == self.PUBLISHED

    @property
    def end(self):
        return self.start + timedelta(days=5)

    def date_for(self, day):
        return self.start + timedelta(days=day)


class Session(models.Model):
    COURSE = 'course'
    TD = 'td'
    TP = 'tp'
    EXAM = 'exam'
    KIND_CHOICES = [(COURSE, 'Course'), (TD, 'TD'), (TP, 'TP'), (EXAM, 'Exam')]

    week = models.ForeignKey(Week, on_delete=models.CASCADE, related_name='sessions')
    day = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    timeslot = models.ForeignKey(TimeSlot, on_delete=models.PROTECT, related_name='sessions')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name='sessions')
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=COURSE)
    groups = models.ManyToManyField(Group, blank=True, related_name='sessions',
                                    help_text='Leave empty when the whole section attends.')
    teacher = models.CharField(max_length=120, blank=True)
    location = models.CharField(max_length=40, blank=True, help_text='Classroom / lab, e.g. E0.05')
    comment = models.CharField(max_length=200, blank=True)
    is_cancelled = models.BooleanField(default=False)
    copied_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='copies')

    class Meta:
        ordering = ['day', 'timeslot__start', 'kind']

    def __str__(self):
        return f'{self.subject} ({self.get_kind_display()}) {DAY_SHORT[self.day]} {self.timeslot}'

    @property
    def date(self):
        return self.week.date_for(self.day)


class Note(models.Model):
    """Notion-like note. `week` empty = pinned to the whole space."""

    space = models.ForeignKey(Space, on_delete=models.CASCADE, related_name='notes')
    week = models.ForeignKey(Week, null=True, blank=True, on_delete=models.CASCADE, related_name='notes')
    title = models.CharField(max_length=120, blank=True)
    content = models.JSONField(default=dict, blank=True, help_text='Editor.js output data.')
    pinned = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-pinned', '-updated_at']

    def __str__(self):
        return self.title or f'Note #{self.pk}'


class AuditLog(models.Model):
    space = models.ForeignKey(Space, null=True, blank=True, on_delete=models.CASCADE, related_name='audit_logs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40)
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # Activity page: latest 100 entries of one space; the log only grows.
        indexes = [models.Index(fields=['space', '-created_at'], name='auditlog_space_recent')]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.user} {self.action}'

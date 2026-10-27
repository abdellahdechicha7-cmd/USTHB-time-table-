"""Dashboard forms. Every queryset that accepts IDs from the client is scoped to a space."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Count

from .models import Group, Session, Space, Subject, TimeSlot, Week

User = get_user_model()


class SpaceForm(forms.ModelForm):
    class Meta:
        model = Space
        fields = ['name', 'slug', 'major', 'section', 'year', 'description', 'is_active']
        help_texts = {'slug': 'Used in URLs. Lowercase letters, numbers and hyphens.'}


class SpaceDeleteForm(forms.Form):
    confirm = forms.CharField(label='Type the slug to confirm')

    def __init__(self, *args, space, **kwargs):
        super().__init__(*args, **kwargs)
        self.space = space

    def clean_confirm(self):
        value = self.cleaned_data['confirm'].strip()
        if value != self.space.slug:
            raise forms.ValidationError('That does not match the slug.')
        return value


class _SpaceScopedNameMixin:
    """Enforce per-space unique names (the space is not a form field)."""

    name_model = None

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        qs = self.name_model.objects.filter(space=self.instance.space, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'"{name}" already exists in this space.')
        return name


class GroupForm(_SpaceScopedNameMixin, forms.ModelForm):
    name_model = Group

    class Meta:
        model = Group
        fields = ['name', 'order']


class SubjectForm(_SpaceScopedNameMixin, forms.ModelForm):
    name_model = Subject

    class Meta:
        model = Subject
        fields = ['name']


class TimeSlotForm(forms.ModelForm):
    class Meta:
        model = TimeSlot
        fields = ['start', 'end']
        widgets = {
            'start': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'end': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }

    def clean(self):
        data = super().clean()
        start, end = data.get('start'), data.get('end')
        if start and end and end <= start:
            raise forms.ValidationError('End time must be after start time.')
        return data


class SessionForm(forms.ModelForm):
    new_subject = forms.CharField(
        label='Or new subject', required=False, max_length=80,
        help_text='Creates the subject in this space if it does not exist.')

    class Meta:
        model = Session
        fields = ['day', 'timeslot', 'subject', 'new_subject', 'kind', 'groups',
                  'teacher', 'location', 'comment', 'is_cancelled']
        widgets = {'groups': forms.CheckboxSelectMultiple}
        labels = {'timeslot': 'Time slot', 'is_cancelled': 'Cancelled'}

    def __init__(self, *args, space, **kwargs):
        super().__init__(*args, **kwargs)
        self.space = space
        self.fields['timeslot'].queryset = TimeSlot.objects.filter(space=space)
        self.fields['subject'].queryset = Subject.objects.filter(space=space)
        self.fields['subject'].required = False
        self.fields['groups'].queryset = Group.objects.filter(space=space)
        self.fields['groups'].help_text = 'Leave all unchecked when the whole section attends.'
        if not self.instance.pk:
            del self.fields['is_cancelled']

    def clean(self):
        data = super().clean()
        new = (data.get('new_subject') or '').strip()
        if not data.get('subject') and not new:
            self.add_error('subject', 'Choose a subject or type a new one.')
        return data

    def save(self, commit=True):
        new = (self.cleaned_data.get('new_subject') or '').strip()
        if new:
            subject = Subject.objects.filter(space=self.space, name__iexact=new).first()
            if subject is None:
                subject = Subject.objects.create(space=self.space, name=new)
            self.instance.subject = subject
        return super().save(commit=commit)


class CopyWeekForm(forms.Form):
    REPLACE, MERGE = 'replace', 'merge'

    source = forms.ModelChoiceField(queryset=Week.objects.none(), label='Copy from week of',
                                    empty_label=None)
    mode = forms.ChoiceField(choices=[(REPLACE, 'Replace'), (MERGE, 'Merge')],
                             initial=REPLACE, widget=forms.RadioSelect, required=False)
    include_notes = forms.BooleanField(required=False, label="Also copy this week's notes")
    confirm_replace = forms.BooleanField(required=False,
                                         label='I understand the current sessions will be removed')

    def __init__(self, *args, space, start, target_has_sessions=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_has_sessions = target_has_sessions
        weeks = (Week.objects.filter(space=space).exclude(start=start)
                 .annotate(n_sessions=Count('sessions')).order_by('-start'))
        self.fields['source'].queryset = weeks
        self.fields['source'].label_from_instance = lambda w: (
            f'{w.start:%d %b %Y} · {w.n_sessions} session{"s" if w.n_sessions != 1 else ""}'
            f' · {w.get_status_display()}')
        if 'source' not in self.initial:
            previous = next((w for w in weeks if w.start < start), None)
            if previous:
                self.initial['source'] = previous.pk

    def clean(self):
        data = super().clean()
        data['mode'] = data.get('mode') or self.REPLACE
        if self.target_has_sessions and data['mode'] == self.REPLACE and not data.get('confirm_replace'):
            self.add_error('confirm_replace', 'Confirm that the current sessions will be replaced.')
        return data


class AdminCreateForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', strip=False,
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='Confirm password', strip=False,
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    spaces = forms.ModelMultipleChoiceField(queryset=Space.objects.all(), required=False,
                                            widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = User
        fields = ['username', 'email']

    def clean(self):
        data = super().clean()
        p1, p2 = data.get('password1'), data.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'The two passwords do not match.')
        elif p1:
            user = User(username=data.get('username', ''), email=data.get('email', ''))
            try:
                validate_password(p1, user)
            except forms.ValidationError as e:
                self.add_error('password1', e)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class AdminEditForm(forms.ModelForm):
    spaces = forms.ModelMultipleChoiceField(queryset=Space.objects.all(), required=False,
                                            widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = User
        fields = ['email']

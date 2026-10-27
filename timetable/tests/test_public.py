from datetime import date, time
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from timetable.models import Group, Note, Session, Space, SpaceMembership, Subject, TimeSlot, Week

TODAY = date(2026, 10, 27)        # Tuesday
WEEK = date(2026, 10, 24)         # its Saturday
PREV = date(2026, 10, 17)


def at(d):
    return mock.patch('timetable.views_public.today', return_value=d)


class PublicPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.space = Space.objects.create(name='MCIL SD B', slug='mcil-sd-b', year='2nd year',
                                         section='B', description='Second year, section B')
        Space.objects.create(name='Hidden', slug='hidden', is_active=False)
        cls.space.create_default_timeslots()
        cls.slots = list(cls.space.timeslots.all())
        cls.g1 = Group.objects.create(space=cls.space, name='G1', order=1)
        cls.g2 = Group.objects.create(space=cls.space, name='G2', order=2)
        cls.algebra = Subject.objects.create(space=cls.space, name='Algèbre 3')
        cls.analysis = Subject.objects.create(space=cls.space, name='Analyse 3')

        cls.prev = Week.objects.create(space=cls.space, start=PREV, status=Week.PUBLISHED)
        cls.week = Week.objects.create(space=cls.space, start=WEEK, status=Week.PUBLISHED,
                                       copied_from=cls.prev)
        cls.dropped = cls.mk(cls.prev, 3, 5, cls.algebra, 'td', [cls.g1])
        src = cls.mk(cls.prev, 1, 0, cls.analysis, 'course', [], location='A1')
        cls.mk(cls.week, 1, 0, cls.analysis, 'course', [], location='B2', copied_from=src)
        cls.mk(cls.week, 3, 1, cls.algebra, 'td', [cls.g1], location='E0.05', teacher='Dr. X')
        cls.mk(cls.week, 3, 2, cls.algebra, 'tp', [cls.g2], cancelled=True)

        cls.next = Week.objects.create(space=cls.space, start=date(2026, 10, 31))  # draft
        cls.mk(cls.next, 1, 0, cls.analysis, 'exam', [])
        Note.objects.create(space=cls.space, title='Pinned info')
        cls.member = get_user_model().objects.create_user('admin1', password='pw')
        SpaceMembership.objects.create(space=cls.space, user=cls.member)

    @classmethod
    def mk(cls, week, day, slot, subject, kind, groups, location='', teacher='',
           cancelled=False, copied_from=None):
        s = Session.objects.create(week=week, day=day, timeslot=cls.slots[slot], subject=subject,
                                   kind=kind, location=location, teacher=teacher,
                                   is_cancelled=cancelled, copied_from=copied_from)
        s.groups.set(groups)
        return s

    def url(self, d=None):
        if d is None:
            return reverse('public:space', args=['mcil-sd-b'])
        return reverse('public:week', args=['mcil-sd-b', d])

    def test_home_lists_active_spaces(self):
        r = self.client.get('/')
        self.assertContains(r, 'MCIL SD B')
        self.assertContains(r, 'Second year, section B')
        self.assertNotContains(r, 'Hidden')
        self.assertIn('max-age=60', r['Cache-Control'])

    def test_current_week_renders(self):
        with at(TODAY):
            r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Week of <span class="nowrap">Sat 24 Oct</span>')
        self.assertContains(r, '<th scope="col"', count=6)
        self.assertContains(r, '<th scope="row"', count=6)
        self.assertContains(r, 'E0.05')
        self.assertContains(r, 'Room changed')
        self.assertContains(r, 'Cancelled')
        self.assertContains(r, '<s>Algèbre 3</s>')
        self.assertContains(r, 'class="is-today"')
        self.assertContains(r, 'data-default-day="3"')
        self.assertNotContains(r, '>This week<')
        self.assertContains(r, 'Removed this week')
        self.assertContains(r, 'not held this week')
        self.assertEqual(list(r.context['pinned_notes'])[0].title, 'Pinned info')
        self.assertIn('public', r['Cache-Control'])
        self.assertIn('max-age=60', r['Cache-Control'])

    def test_group_data_attributes(self):
        with at(TODAY):
            r = self.client.get(self.url())
        self.assertContains(r, 'data-groups="G1"')
        self.assertContains(r, 'data-groups="G2"')
        self.assertContains(r, 'data-groups=""')
        self.assertContains(r, 'data-group="G2"')
        self.assertContains(r, 'aria-pressed="true">All<')

    def test_other_week_shows_this_week_link(self):
        with at(TODAY):
            r = self.client.get(self.url('2026-10-19'))  # Monday -> snaps to Sat 17
        self.assertEqual(r.context['start'], PREV)
        self.assertContains(r, '>This week<')
        self.assertNotContains(r, 'is-today')
        self.assertContains(r, 'data-default-day="1"')

    def test_invalid_week_404(self):
        self.assertEqual(self.client.get(self.url('2026-13-45')).status_code, 404)
        self.assertEqual(self.client.get(self.url('nope')).status_code, 404)
        self.assertEqual(self.client.get(self.url() + '?date=bad').status_code, 404)

    def test_date_jump_redirects(self):
        r = self.client.get(self.url() + '?date=2026-10-29')
        self.assertRedirects(r, self.url('2026-10-24'), fetch_redirect_response=False)

    def test_inactive_space_404(self):
        self.assertEqual(self.client.get(reverse('public:space', args=['hidden'])).status_code, 404)

    def test_friday_shows_next_week(self):
        with at(date(2026, 10, 30)):  # Friday
            r = self.client.get(self.url())
        self.assertEqual(r.context['start'], date(2026, 10, 31))
        self.assertTrue(r.context['is_current'])

    def test_draft_hidden_from_anonymous(self):
        with at(TODAY):
            r = self.client.get(self.url('2026-10-31'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "hasn't been published yet")
        self.assertNotContains(r, 'Draft preview')
        self.assertNotIn('rows', r.context)
        self.assertNotContains(r, 'class="sess')
        self.assertIsNone(r.context['week'])
        self.assertEqual(r.context['fallback'], self.week)
        self.assertContains(r, self.url('2026-10-24'))

    def test_draft_visible_to_member_and_private(self):
        self.client.force_login(self.member)
        with at(TODAY):
            r = self.client.get(self.url('2026-10-31'))
        self.assertContains(r, "Draft preview — students can't see this")
        self.assertEqual(r.context['week'], self.next)
        self.assertIn('private', r['Cache-Control'])
        self.assertNotIn('public', r['Cache-Control'])

    def test_missing_week_without_fallback(self):
        with at(TODAY):
            r = self.client.get(self.url('2020-01-04'))
        self.assertContains(r, "hasn't been published yet")
        self.assertIsNone(r.context['fallback'])

    def test_query_count_constant(self):
        def count():
            with at(TODAY), CaptureQueriesContext(connection) as ctx:
                self.client.get(self.url())
            return len(ctx)

        before = count()
        for day in range(6):
            for slot in range(6):
                self.mk(self.week, day, slot, self.algebra, 'td', [self.g1, self.g2], location='X')
        self.assertEqual(count(), before)
        self.assertLessEqual(before, 15)

from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from timetable.models import AuditLog, Group, Session, Space, SpaceMembership, Subject, TimeSlot, Week

User = get_user_model()

W1 = date(2026, 10, 17)  # Saturday
W2 = date(2026, 10, 24)  # Saturday


class DashboardBase(TestCase):
    def setUp(self):
        self.space = Space.objects.create(name='L2 Info A', slug='l2-info-a')
        self.space.create_default_timeslots()
        self.other = Space.objects.create(name='L2 Info B', slug='l2-info-b')
        self.other.create_default_timeslots()

        self.owner = User.objects.create_superuser('owner', 'o@x.dz', 'pw-owner-123')
        self.admin = User.objects.create_user('admin', password='pw-admin-123')
        self.stranger = User.objects.create_user('stranger', password='pw-stranger-123')
        SpaceMembership.objects.create(space=self.space, user=self.admin)

        self.slot = self.space.timeslots.order_by('start').first()
        self.subject = Subject.objects.create(space=self.space, name='Algorithms')
        self.g1 = Group.objects.create(space=self.space, name='G1')
        self.other_slot = self.other.timeslots.first()
        self.other_subject = Subject.objects.create(space=self.other, name='Physics')
        self.other_group = Group.objects.create(space=self.other, name='G1')

        self.week1 = Week.objects.create(space=self.space, start=W1, status=Week.PUBLISHED)
        self.s1 = Session.objects.create(week=self.week1, day=0, timeslot=self.slot,
                                         subject=self.subject, kind='course')
        self.client.force_login(self.admin)

    def url(self, name, *args):
        return reverse(f'dashboard:{name}', args=args)

    def session_data(self, **kw):
        data = {'day': 2, 'timeslot': self.slot.pk, 'subject': self.subject.pk, 'kind': 'td',
                'teacher': 'Dr. X', 'location': 'E0.05', 'comment': '', 'new_subject': ''}
        data.update(kw)
        return data


class AccessTests(DashboardBase):
    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        for url in [self.url('home'), self.url('week', self.space.slug, W1.isoformat()),
                    self.url('settings', self.space.slug), self.url('admins')]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn(reverse('login'), r['Location'])

    def test_non_member_forbidden(self):
        self.client.force_login(self.stranger)
        for url in [self.url('week', self.space.slug, W1.isoformat()),
                    self.url('settings', self.space.slug), self.url('activity', self.space.slug),
                    self.url('session_edit', self.space.slug, self.s1.pk)]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.post(self.url('week_publish', self.space.slug, W1.isoformat()))
        self.assertEqual(r.status_code, 403)

    def test_home_lists_only_managed_spaces(self):
        r = self.client.get(self.url('home'))
        self.assertContains(r, 'L2 Info A')
        self.assertNotContains(r, 'L2 Info B')
        self.assertNotContains(r, 'New space')

    def test_superuser_only_views_forbidden_for_space_admins(self):
        for url in [self.url('space_create'), self.url('space_edit', self.space.slug),
                    self.url('space_delete', self.space.slug), self.url('admins'),
                    self.url('admin_create'), self.url('admin_edit', self.stranger.pk),
                    self.url('admin_password', self.stranger.pk)]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        r = self.client.post(self.url('admin_toggle_active', self.stranger.pk))
        self.assertEqual(r.status_code, 403)
        self.stranger.refresh_from_db()
        self.assertTrue(self.stranger.is_active)

    def test_mutations_require_post(self):
        r = self.client.get(self.url('session_delete', self.space.slug, self.s1.pk))
        self.assertEqual(r.status_code, 405)


class SessionTests(DashboardBase):
    def test_member_can_create_session_and_week_is_created(self):
        url = self.url('session_create', self.space.slug, W2.isoformat())
        self.assertEqual(self.client.get(url + f'?day=2&slot={self.slot.pk}').status_code, 200)
        r = self.client.post(url, self.session_data(groups=[self.g1.pk]))
        self.assertRedirects(r, self.url('week', self.space.slug, W2.isoformat()))
        wk = Week.objects.get(space=self.space, start=W2)
        self.assertEqual(wk.status, Week.DRAFT)
        s = wk.sessions.get()
        self.assertEqual(list(s.groups.all()), [self.g1])
        self.assertTrue(AuditLog.objects.filter(space=self.space, action='session.create').exists())

    def test_partial_form_fragment(self):
        r = self.client.get(self.url('session_edit', self.space.slug, self.s1.pk) + '?partial=1')
        self.assertContains(r, 'id="session-form"')
        self.assertNotContains(r, '<html')

    def test_new_subject_created_in_space(self):
        url = self.url('session_create', self.space.slug, W1.isoformat())
        self.client.post(url, self.session_data(subject='', new_subject='Databases'))
        self.assertTrue(Subject.objects.filter(space=self.space, name='Databases').exists())

    def test_cross_space_ids_rejected(self):
        url = self.url('session_create', self.space.slug, W1.isoformat())
        before = Session.objects.count()
        for bad in [{'timeslot': self.other_slot.pk}, {'subject': self.other_subject.pk},
                    {'groups': [self.other_group.pk]}]:
            r = self.client.post(url, self.session_data(**bad))
            self.assertEqual(r.status_code, 200, bad)  # re-rendered with errors
        self.assertEqual(Session.objects.count(), before)

        # Session of another space -> 404 through this space's URL
        other_week = Week.objects.create(space=self.other, start=W1)
        foreign = Session.objects.create(week=other_week, day=0, timeslot=self.other_slot,
                                         subject=self.other_subject)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url('session_edit', self.space.slug, foreign.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('session_delete', self.space.slug, foreign.pk)).status_code, 404)
        # Settings objects of another space -> 404
        r = self.client.post(self.url('settings_delete', self.space.slug, 'group', self.other_group.pk))
        self.assertEqual(r.status_code, 404)

    def test_edit_cancel_delete(self):
        edit = self.url('session_edit', self.space.slug, self.s1.pk)
        self.client.post(edit, self.session_data(day=0, location='LAB1'))
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.location, 'LAB1')
        self.client.post(self.url('session_toggle_cancel', self.space.slug, self.s1.pk))
        self.s1.refresh_from_db()
        self.assertTrue(self.s1.is_cancelled)
        self.client.post(self.url('session_delete', self.space.slug, self.s1.pk))
        self.assertFalse(Session.objects.filter(pk=self.s1.pk).exists())


class WeekTests(DashboardBase):
    def test_space_redirects_to_current_week(self):
        r = self.client.get(self.url('space', self.space.slug))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/w/', r['Location'])

    def test_empty_week_does_not_create_row(self):
        r = self.client.get(self.url('week', self.space.slug, W2.isoformat()))
        self.assertContains(r, 'Copy week')
        self.assertContains(r, 'Start blank')
        self.assertFalse(Week.objects.filter(space=self.space, start=W2).exists())

    def test_publish_toggle(self):
        url = self.url('week_publish', self.space.slug, W2.isoformat())
        self.client.post(url, {'action': 'publish'})
        self.assertEqual(Week.objects.get(space=self.space, start=W2).status, Week.PUBLISHED)
        self.client.post(url, {'action': 'unpublish'})
        self.assertEqual(Week.objects.get(space=self.space, start=W2).status, Week.DRAFT)

    def test_copy_replace_and_merge(self):
        url = self.url('week_copy', self.space.slug, W2.isoformat())
        self.client.post(url, {'source': self.week1.pk, 'mode': 'replace'})
        wk2 = Week.objects.get(space=self.space, start=W2)
        self.assertEqual(wk2.sessions.count(), 1)
        self.assertEqual(wk2.copied_from, self.week1)

        # Merge adds on top
        self.client.post(url, {'source': self.week1.pk, 'mode': 'merge'})
        self.assertEqual(wk2.sessions.count(), 2)

        # Replace without confirmation is refused when sessions exist
        self.client.post(url, {'source': self.week1.pk, 'mode': 'replace'})
        self.assertEqual(wk2.sessions.count(), 2)
        self.client.post(url, {'source': self.week1.pk, 'mode': 'replace', 'confirm_replace': 'on'})
        self.assertEqual(wk2.sessions.count(), 1)

    def test_copy_rejects_foreign_week(self):
        foreign = Week.objects.create(space=self.other, start=W1)
        url = self.url('week_copy', self.space.slug, W2.isoformat())
        self.client.post(url, {'source': foreign.pk, 'mode': 'replace'})
        self.assertFalse(Week.objects.filter(space=self.space, start=W2).exists())

    def test_start_blank(self):
        self.client.post(self.url('week_start', self.space.slug, W2.isoformat()))
        self.assertTrue(Week.objects.filter(space=self.space, start=W2).exists())

    def _count_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(self.url('week', self.space.slug, W1.isoformat()))
        self.assertEqual(r.status_code, 200)
        return len(ctx.captured_queries)

    def test_editor_query_count_is_constant(self):
        few = self._count_queries()
        slots = list(self.space.timeslots.all())
        for day in range(6):
            for ts in slots:
                s = Session.objects.create(week=self.week1, day=day, timeslot=ts, subject=self.subject)
                s.groups.add(self.g1)
        self.assertEqual(self._count_queries(), few)
        self.assertLessEqual(few, 15)


class SettingsTests(DashboardBase):
    def test_group_crud_and_duplicate(self):
        add = self.url('settings_add', self.space.slug, 'group')
        self.client.post(add, {'new-name': 'G2', 'new-order': 2})
        self.assertTrue(self.space.groups.filter(name='G2').exists())
        self.client.post(add, {'new-name': 'g1', 'new-order': 3})
        self.assertEqual(self.space.groups.filter(name__iexact='g1').count(), 1)

    def test_timeslot_validation(self):
        add = self.url('settings_add', self.space.slug, 'slot')
        n = self.space.timeslots.count()
        self.client.post(add, {'new-start': '18:00', 'new-end': '17:00'})
        self.assertEqual(self.space.timeslots.count(), n)
        self.client.post(add, {'new-start': '18:00', 'new-end': '19:30'})
        self.assertEqual(self.space.timeslots.count(), n + 1)

    def test_protected_delete_is_friendly(self):
        r = self.client.post(self.url('settings_delete', self.space.slug, 'subject', self.subject.pk), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'cannot be deleted')
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())
        r = self.client.post(self.url('settings_delete', self.space.slug, 'slot', self.slot.pk), follow=True)
        self.assertContains(r, 'cannot be deleted')
        self.assertTrue(TimeSlot.objects.filter(pk=self.slot.pk).exists())


class SuperuserTests(DashboardBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_create_space_makes_timeslots(self):
        r = self.client.post(self.url('space_create'), {'name': 'M1 SII', 'slug': 'm1-sii', 'is_active': 'on'})
        space = Space.objects.get(slug='m1-sii')
        self.assertRedirects(r, self.url('settings', 'm1-sii'))
        self.assertEqual(space.timeslots.count(), 6)

    def test_delete_space_requires_slug(self):
        url = self.url('space_delete', self.space.slug)
        self.client.post(url, {'confirm': 'nope'})
        self.assertTrue(Space.objects.filter(pk=self.space.pk).exists())
        self.client.post(url, {'confirm': self.space.slug})
        self.assertFalse(Space.objects.filter(pk=self.space.pk).exists())

    def test_create_admin_with_spaces(self):
        r = self.client.post(self.url('admin_create'), {
            'username': 'newbie', 'email': '', 'password1': 'Strong-pass-9081', 'password2': 'Strong-pass-9081',
            'spaces': [self.space.pk, self.other.pk]})
        self.assertRedirects(r, self.url('admins'))
        u = User.objects.get(username='newbie')
        self.assertTrue(u.check_password('Strong-pass-9081'))
        self.assertEqual(u.space_memberships.count(), 2)

    def test_weak_password_rejected(self):
        self.client.post(self.url('admin_create'), {'username': 'weak', 'password1': '123', 'password2': '123'})
        self.assertFalse(User.objects.filter(username='weak').exists())

    def test_edit_assignments(self):
        self.client.post(self.url('admin_edit', self.admin.pk), {'email': '', 'spaces': [self.other.pk]})
        self.assertEqual(list(self.admin.space_memberships.values_list('space__slug', flat=True)), ['l2-info-b'])

    def test_cannot_deactivate_self(self):
        self.client.post(self.url('admin_toggle_active', self.owner.pk))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.client.post(self.url('admin_toggle_active', self.admin.pk))
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)

    def test_set_password(self):
        self.client.post(self.url('admin_password', self.admin.pk),
                         {'new_password1': 'Another-pass-5521', 'new_password2': 'Another-pass-5521'})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('Another-pass-5521'))

    def test_admin_pages_render(self):
        for url in [self.url('home'), self.url('admins'), self.url('admin_create'),
                    self.url('space_create'), self.url('space_edit', self.space.slug),
                    self.url('settings', self.space.slug), self.url('activity', self.space.slug),
                    self.url('week', self.space.slug, W2.isoformat())]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

"""Create the 'MCIL.SD Section B' space from the official S1 2026/2027 timetable.

Last week = the official timetable; this week = a copy of it with the real
changes (new TP POO sessions, cancelled TDs), so the change badges show.
Safe to re-run: it wipes and rebuilds the demo space.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from timetable.models import Group, Note, Session, Space, Subject, Week
from timetable.services import copy_week, current_week_start

C, TD, TP = Session.COURSE, Session.TD, Session.TP
SAT, SUN, MON, TUE, WED, THU = range(6)

# (day, slot index, subject, kind, groups, teacher, location)
OFFICIAL = [
    (SUN, 0, 'Algèbre 3', C, [], 'Oudrar', 'D8'),
    (SUN, 1, 'Topologie', C, [], 'Djaib ép Radjah', 'D8'),
    (MON, 0, 'Analyse 3', C, [], 'Chaoui', 'R8'),
    (MON, 1, 'Programmation orientée objet', C, [], 'Bokhari', 'R8'),
    (MON, 2, 'Algèbre 3', TD, ['G1'], 'Oudrar ép Abchiche', '362'),
    (MON, 2, 'Analyse 3', TD, ['G2'], 'Chaoui', '387'),
    (MON, 3, 'Analyse 3', TD, ['G1'], 'Chaoui', '135D'),
    (TUE, 3, 'Analyse 3', C, [], 'Chaoui', '415T'),
    (TUE, 4, 'Complexité', TD, ['G1'], 'Yagouni', '437'),
    (TUE, 4, 'Analyse 3', TD, ['G2'], 'Chaoui', '439'),
    (TUE, 5, 'Algèbre 3', TD, ['G1'], '', '437'),
    (TUE, 5, 'Analyse 3', TD, ['G2'], '', '439'),
    (WED, 0, 'Complexité', TD, ['G2'], 'Yagouni', 'C202'),
    (WED, 2, 'Analyse 3', TD, ['G1'], 'Chaoui', '445'),
    (WED, 2, 'Topologie', TD, ['G2'], 'Fernane', '447'),
    (WED, 3, 'Probabilité 1', C, [], 'Adjoudj', '415T'),
    (WED, 4, 'Complexité', C, [], 'Yagouni', '415T'),
    (THU, 0, 'Topologie', C, [], 'Djaib ép Radjah', 'E2'),
    (THU, 1, 'Probabilité 1', C, [], 'Adjoudj', 'E2'),
    (THU, 2, 'Probabilité 1', TD, ['G1'], 'Zaboot ép Sadoudi', '458'),
    (THU, 2, 'Algèbre 3', TD, ['G2'], 'Oudrar ép Abchiche', '460'),
    (THU, 3, 'Topologie', TD, ['G1'], 'Djaib ép Radjah', '458'),
    (THU, 3, 'Probabilité 1', TD, ['G2'], 'Zaboot ép Sadoudi', '460'),
]


class Command(BaseCommand):
    help = 'Seed the MCIL.SD Section B demo space.'

    @transaction.atomic
    def handle(self, *args, **opts):
        Space.objects.filter(slug='mcil-sd-b').delete()
        space = Space.objects.create(
            name='MCIL.SD · Section B', slug='mcil-sd-b', major='MCIL.SD', section='B',
            year='2nd year', description='Semester 1 · 2026/2027',
        )
        space.create_default_timeslots()
        slots = list(space.timeslots.all())
        groups = {n: Group.objects.create(space=space, name=n, order=i) for i, n in enumerate(['G1', 'G2'])}
        subjects = {}

        def subject(name):
            if name not in subjects:
                subjects[name] = Subject.objects.create(space=space, name=name)
            return subjects[name]

        this_start = current_week_start()
        last = Week.objects.create(space=space, start=this_start - timedelta(days=7), status=Week.PUBLISHED)
        for day, slot, name, kind, gs, teacher, loc in OFFICIAL:
            s = Session.objects.create(week=last, day=day, timeslot=slots[slot], subject=subject(name),
                                       kind=kind, teacher=teacher, location=loc)
            s.groups.set([groups[g] for g in gs])

        this = Week.objects.create(space=space, start=this_start, status=Week.PUBLISHED)
        copy_week(last, this)

        def find(day, slot, name, kind, group=None):
            qs = this.sessions.filter(day=day, timeslot=slots[slot], subject__name=name, kind=kind)
            if group:
                qs = qs.filter(groups=groups[group])
            return qs.get()

        # This week's real changes.
        for args in [(TUE, 4, 'Complexité', TD, 'G1'), (TUE, 5, 'Algèbre 3', TD, 'G1'),
                     (TUE, 5, 'Analyse 3', TD, 'G2'), (WED, 0, 'Complexité', TD, 'G2')]:
            s = find(*args)
            s.is_cancelled = True
            s.save()

        topo = find(THU, 0, 'Topologie', C)
        topo.kind = TD
        topo.save()
        topo.groups.set([groups['G1']])

        poo = subject('Programmation orientée objet')
        for slot, g in [(2, 'G1'), (3, 'G2')]:
            s = Session.objects.create(week=this, day=SUN, timeslot=slots[slot], subject=poo,
                                       kind=TP, location='E0.05', teacher='Bokhari')
            s.groups.set([groups[g]])

        Note.objects.create(space=space, pinned=True, title='Welcome', content={'blocks': [
            {'type': 'paragraph', 'data': {'text': 'This page is updated every week by the section admins.'}},
            {'type': 'list', 'data': {'style': 'unordered', 'items': [
                'Use the <b>G1 / G2</b> filter to see only your group.',
                'Changed sessions are marked <i>Moved</i>, <i>New</i> or <i>Cancelled</i>.',
            ]}},
        ]})
        Note.objects.create(space=space, week=this, title='This week', content={'blocks': [
            {'type': 'paragraph', 'data': {'text': 'TP POO starts this Sunday in room E0.05.'}},
            {'type': 'checklist', 'data': {'items': [
                {'text': 'Bring your laptop', 'checked': False},
                {'text': 'Install a Java JDK', 'checked': False},
            ]}},
        ]})

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {space} — weeks {last.start} and {this.start}. Open /s/{space.slug}/'))

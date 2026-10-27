"""Public, read-only pages: list of sections and the weekly timetable."""

from datetime import timedelta

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.cache import patch_cache_control

from .models import DAY_SHORT, Note, Space, Week
from .services import (build_grid, can_edit_space, current_week_start, parse_week,
                       removed_sessions, today_day_index, week_sessions)

CHANGE_LABELS = {
    'cancelled': 'Cancelled',
    'new': 'New',
    'moved': 'Moved',
    'room': 'Room changed',
    'changed': 'Changed',
}


def today():
    """Indirection so tests can pin the date."""
    return timezone.localdate()


def group_key(name):
    """Token used in data-groups / data-group (space separated list)."""
    return name.replace(' ', '_')


def _cache(request, response):
    if request.user.is_authenticated:
        patch_cache_control(response, private=True, no_cache=True)
    else:
        patch_cache_control(response, public=True, max_age=60)
    return response


def home(request):
    spaces = Space.objects.filter(is_active=True).only('name', 'slug', 'year', 'description')
    return _cache(request, render(request, 'public/home.html', {'spaces': spaces}))


def _parse_or_404(value):
    try:
        return parse_week(value)
    except (ValueError, OverflowError):
        raise Http404('Invalid week')


def space(request, slug, week=None):
    space = get_object_or_404(Space, slug=slug, is_active=True)

    # No-JS "jump to date" form submits ?date=YYYY-MM-DD.
    jump = request.GET.get('date', '').strip()
    if jump:
        return redirect('public:week', slug=space.slug, week=_parse_or_404(jump).isoformat())

    now = today()
    current = current_week_start(now)
    start = _parse_or_404(week) if week is not None else current
    is_current = start == current

    editor = can_edit_space(request.user, space)
    week_obj = (Week.objects.filter(space=space, start=start)
                .select_related('copied_from').first())
    visible = week_obj is not None and (week_obj.is_published or editor)

    ctx = {
        'space': space,
        'meta_line': ' · '.join(p for p in (
            space.year, space.major, f'Section {space.section}' if space.section else '') if p),
        'start': start,
        'end': start + timedelta(days=5),
        'prev_week': (start - timedelta(days=7)).isoformat(),
        'next_week': (start + timedelta(days=7)).isoformat(),
        'is_current': is_current,
        'week': week_obj if visible else None,
        'is_draft_preview': visible and not week_obj.is_published,
        'groups': [],
        'pinned_notes': Note.objects.filter(space=space, week=None).select_related('author'),
        'week_notes': Note.objects.none(),
    }

    if visible:
        timeslots = list(space.timeslots.all())
        rows = build_grid(week_obj, timeslots, week_sessions(week_obj))
        today_idx = today_day_index(now) if is_current else None
        total = 0
        for row in rows:
            row['short'] = DAY_SHORT[row['day']]
            row['is_today'] = row['day'] == today_idx
            row['count'] = 0
            for cell in row['cells']:
                for s in cell:
                    s.group_key = ' '.join(group_key(g.name) for g in s.groups.all())
                    s.change_labels = [(c, CHANGE_LABELS[c]) for c in s.changes]
                    row['count'] += 1
            total += row['count']
        # Mobile day lists: flatten each row's cells in time order.
        for row in rows:
            row['sessions'] = [s for cell in row['cells'] for s in cell]

        removed = list(removed_sessions(week_obj))
        for s in removed:
            s.day_short = DAY_SHORT[s.day]
            s.group_key = ' '.join(group_key(g.name) for g in s.groups.all())

        ctx.update({
            'timeslots': timeslots,
            'rows': rows,
            'total_sessions': total,
            'default_day': today_idx if today_idx is not None else 1,
            'removed': removed,
            'groups': [(g.name, group_key(g.name)) for g in space.groups.all()],
            'week_notes': week_obj.notes.select_related('author'),
        })
    else:
        ctx['fallback'] = (Week.objects
                           .filter(space=space, status=Week.PUBLISHED, start__lt=start)
                           .order_by('-start').only('start').first())

    response = render(request, 'public/space.html', ctx)
    if ctx['is_draft_preview']:
        patch_cache_control(response, private=True, no_cache=True, no_store=True)
        return response
    return _cache(request, response)

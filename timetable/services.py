"""Core timetable logic shared by the public site and the dashboard."""

from datetime import date, timedelta
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import AuditLog, Note, Session, Space, Week

SATURDAY = 5  # date.weekday() value
# Accepted week range. Keeps +/- 7 day arithmetic away from date.min/date.max
# (OverflowError -> 500) and stops admins creating weeks in year 0001 by URL.
MIN_YEAR, MAX_YEAR = 2000, 2100


# ---------------------------------------------------------------- weeks

def week_start_for(d: date) -> date:
    """Saturday on or before `d`."""
    return d - timedelta(days=(d.weekday() - SATURDAY) % 7)


def current_week_start(today: date | None = None) -> date:
    """The week students care about now. On Friday (day off) it's the coming week."""
    today = today or timezone.localdate()
    if today.weekday() == 4:  # Friday
        return today + timedelta(days=1)
    return week_start_for(today)


def parse_week(value: str) -> date:
    """Parse 'YYYY-MM-DD' and snap it to its Saturday. Raises ValueError."""
    d = date.fromisoformat(value)
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        raise ValueError(f'Week must be between {MIN_YEAR} and {MAX_YEAR}.')
    return week_start_for(d)


def today_day_index(today: date | None = None):
    """0..5 for Sat..Thu, None on Friday."""
    today = today or timezone.localdate()
    idx = (today.weekday() - SATURDAY) % 7
    return idx if idx <= 5 else None


# ---------------------------------------------------------------- permissions

def can_edit_space(user, space: Space) -> bool:
    if not user.is_authenticated:
        return False
    return user.is_superuser or space.memberships.filter(user=user).exists()


def space_admin_required(view):
    """Decorator for views taking `slug`; injects `space` and enforces membership."""

    @wraps(view)
    def wrapper(request, slug, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        space = get_object_or_404(Space, slug=slug)
        if not can_edit_space(request.user, space):
            raise PermissionDenied
        return view(request, space, *args, **kwargs)

    return wrapper


def log(user, space, action, detail=''):
    AuditLog.objects.create(user=user, space=space, action=action, detail=detail[:255])


# ---------------------------------------------------------------- copy

@transaction.atomic
def copy_week(source: Week, target: Week, *, replace=True, include_notes=False) -> int:
    """Copy sessions (and optionally week notes) from `source` into `target`.

    replace=True wipes the target's sessions first; otherwise copies are added.
    Cancelled sessions are not carried over. Returns the number of sessions copied.
    """
    if source.space_id != target.space_id or source.pk == target.pk:
        raise ValueError('Can only copy between different weeks of the same space.')
    if replace:
        target.sessions.all().delete()

    count = 0
    for s in source.sessions.filter(is_cancelled=False).prefetch_related('groups'):
        groups = list(s.groups.all())
        new = Session.objects.create(
            week=target, day=s.day, timeslot_id=s.timeslot_id, subject_id=s.subject_id,
            kind=s.kind, teacher=s.teacher, location=s.location, comment=s.comment,
            copied_from=s,
        )
        if groups:
            new.groups.set(groups)
        count += 1

    if include_notes:
        Note.objects.bulk_create(
            Note(space=n.space, week=target, title=n.title, content=n.content, author=n.author)
            for n in source.notes.all()
        )

    target.copied_from = source
    target.save(update_fields=['copied_from', 'updated_at'])
    return count


# ---------------------------------------------------------------- changes

def session_changes(session: Session) -> list[str]:
    """Badges describing how a session differs from the week it was copied from.

    Possible values: 'cancelled', 'new', 'moved', 'room', 'changed'.
    Expects `copied_from` (with its groups) to be prefetched for efficiency.
    """
    changes = []
    if session.is_cancelled:
        changes.append('cancelled')
    src = session.copied_from
    if src is None:
        if session.week.copied_from_id:
            changes.append('new')
        return changes
    if src.day != session.day or src.timeslot_id != session.timeslot_id:
        changes.append('moved')
    if src.location != session.location:
        changes.append('room')
    if (src.subject_id != session.subject_id or src.kind != session.kind
            or src.teacher != session.teacher
            or {g.pk for g in src.groups.all()} != {g.pk for g in session.groups.all()}):
        changes.append('changed')
    return changes


def removed_sessions(week: Week):
    """Sessions of the source week that no longer exist in `week`."""
    if not week.copied_from_id:
        return Session.objects.none()
    kept = week.sessions.exclude(copied_from=None).values('copied_from_id')
    return (week.copied_from.sessions.filter(is_cancelled=False).exclude(pk__in=kept)
            .select_related('subject', 'timeslot').prefetch_related('groups'))


def week_sessions(week: Week):
    """All sessions of a week, with everything templates need preloaded."""
    return (week.sessions
            .select_related('subject', 'timeslot', 'week', 'copied_from')
            .prefetch_related('groups', 'copied_from__groups'))


def build_grid(week: Week, timeslots, sessions=None):
    """Return rows: [{'day', 'label', 'date', 'cells': [[session, ...] per timeslot]}].

    Each session gets a `.changes` list attached.
    """
    from .models import DAY_CHOICES

    sessions = list(sessions if sessions is not None else week_sessions(week))
    slot_index = {ts.pk: i for i, ts in enumerate(timeslots)}
    rows = [
        {'day': d, 'label': label, 'date': week.date_for(d), 'cells': [[] for _ in timeslots]}
        for d, label in DAY_CHOICES
    ]
    for s in sessions:
        s.changes = session_changes(s)
        i = slot_index.get(s.timeslot_id)
        if i is not None:
            rows[s.day]['cells'][i].append(s)
    return rows

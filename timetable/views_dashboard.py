"""Admin dashboard: spaces, settings, admins and the week editor."""

from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from .forms import (AdminCreateForm, AdminEditForm, CopyWeekForm, GroupForm, SessionForm,
                    SpaceDeleteForm, SpaceForm, SubjectForm, TimeSlotForm)
from .models import DAY_CHOICES, AuditLog, Group, Session, Space, SpaceMembership, Subject, TimeSlot, Week
from .services import (build_grid, copy_week, current_week_start, log, parse_week,
                       removed_sessions, space_admin_required, week_sessions)

User = get_user_model()


# ---------------------------------------------------------------- helpers

def superuser_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def _week_start(value):
    try:
        return parse_week(value)
    except ValueError:
        raise Http404('Invalid week')


def _week_url(space, start):
    return reverse('dashboard:week', args=[space.slug, start.isoformat()])


def _touch(week):
    week.save()


def _space_session(space, pk):
    return get_object_or_404(Session.objects.select_related('week', 'subject', 'timeslot'),
                             pk=pk, week__space=space)


# ---------------------------------------------------------------- home

@login_required
def home(request):
    user = request.user
    spaces = Space.objects.all() if user.is_superuser else Space.objects.filter(memberships__user=user)
    return render(request, 'dashboard/home.html', {
        'spaces': spaces.order_by('name'),
        'week': current_week_start().isoformat(),
    })


# ---------------------------------------------------------------- spaces (superuser)

@superuser_required
def space_create(request):
    form = SpaceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        space = form.save()
        space.create_default_timeslots()
        log(request.user, space, 'space.create', space.name)
        messages.success(request, f'Space "{space.name}" created.')
        return redirect('dashboard:settings', slug=space.slug)
    return render(request, 'dashboard/space_form.html', {'form': form, 'creating': True})


@superuser_required
def space_edit(request, slug):
    space = get_object_or_404(Space, slug=slug)
    form = SpaceForm(request.POST or None, instance=space)
    if request.method == 'POST' and form.is_valid():
        space = form.save()
        log(request.user, space, 'space.edit', space.name)
        messages.success(request, 'Space saved.')
        return redirect('dashboard:settings', slug=space.slug)
    return render(request, 'dashboard/space_form.html', {'form': form, 'space': space, 'creating': False})


@superuser_required
def space_delete(request, slug):
    space = get_object_or_404(Space, slug=slug)
    form = SpaceDeleteForm(request.POST or None, space=space)
    if request.method == 'POST' and form.is_valid():
        name = space.name
        log(request.user, None, 'space.delete', f'{name} ({space.slug})')
        with transaction.atomic():
            # Sessions PROTECT timeslots/subjects, so remove weeks first.
            Session.objects.filter(week__space=space).delete()
            space.delete()
        messages.success(request, f'Space "{name}" deleted.')
        return redirect('dashboard:home')
    return render(request, 'dashboard/space_delete.html', {'form': form, 'space': space})


# ---------------------------------------------------------------- space settings

@space_admin_required
def space_settings(request, space):
    return render(request, 'dashboard/settings.html', {
        'space': space,
        'groups': space.groups.all(),
        'timeslots': space.timeslots.all(),
        'subjects': space.subjects.all(),
        'group_form': GroupForm(prefix='new'),
        'slot_form': TimeSlotForm(prefix='new'),
        'subject_form': SubjectForm(prefix='new'),
    })


_SETTINGS_KINDS = {
    'group': (Group, GroupForm, 'Group'),
    'slot': (TimeSlot, TimeSlotForm, 'Time slot'),
    'subject': (Subject, SubjectForm, 'Subject'),
}


def _form_errors(form):
    return ' '.join(str(e) for errs in form.errors.values() for e in errs)


@require_POST
@space_admin_required
def settings_save(request, space, kind, pk=None):
    if kind not in _SETTINGS_KINDS:
        raise Http404
    model, form_class, label = _SETTINGS_KINDS[kind]
    instance = get_object_or_404(model, pk=pk, space=space) if pk else model(space=space)
    form = form_class(request.POST, instance=instance, prefix=None if pk else 'new')
    if form.is_valid():
        obj = form.save()
        if kind == 'slot' and not pk:
            obj.order = space.timeslots.count()
            obj.save(update_fields=['order'])
        log(request.user, space, f'{kind}.{"edit" if pk else "add"}', str(obj))
        messages.success(request, f'{label} saved.')
    else:
        messages.error(request, f'{label} not saved: {_form_errors(form)}')
    return redirect(reverse('dashboard:settings', args=[space.slug]) + f'#{kind}s')


@require_POST
@space_admin_required
def settings_delete(request, space, kind, pk):
    if kind not in _SETTINGS_KINDS:
        raise Http404
    model, _, label = _SETTINGS_KINDS[kind]
    obj = get_object_or_404(model, pk=pk, space=space)
    name = str(obj)
    try:
        obj.delete()
    except ProtectedError:
        messages.error(request, f'{label} "{name}" is used by sessions and cannot be deleted. '
                                'Change or delete those sessions first.')
    else:
        log(request.user, space, f'{kind}.delete', name)
        messages.success(request, f'{label} "{name}" deleted.')
    return redirect(reverse('dashboard:settings', args=[space.slug]) + f'#{kind}s')


@space_admin_required
def activity(request, space):
    logs = AuditLog.objects.filter(space=space).select_related('user')[:100]
    return render(request, 'dashboard/activity.html', {'space': space, 'logs': logs})


# ---------------------------------------------------------------- admins (superuser)

@superuser_required
def admins(request):
    users = User.objects.order_by('-is_active', 'username').prefetch_related('space_memberships__space')
    return render(request, 'dashboard/admins.html', {'users': users})


def _set_spaces(user, spaces):
    wanted = {s.pk for s in spaces}
    SpaceMembership.objects.filter(user=user).exclude(space_id__in=wanted).delete()
    have = set(SpaceMembership.objects.filter(user=user).values_list('space_id', flat=True))
    SpaceMembership.objects.bulk_create(SpaceMembership(user=user, space_id=pk) for pk in wanted - have)


@superuser_required
def admin_create(request):
    form = AdminCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            _set_spaces(user, form.cleaned_data['spaces'])
        log(request.user, None, 'admin.create', user.username)
        messages.success(request, f'Admin "{user.username}" created.')
        return redirect('dashboard:admins')
    return render(request, 'dashboard/admin_form.html', {'form': form, 'creating': True})


@superuser_required
def admin_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    initial = {'spaces': list(Space.objects.filter(memberships__user=target))}
    form = AdminEditForm(request.POST or None, instance=target, initial=initial)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            _set_spaces(target, form.cleaned_data['spaces'])
        log(request.user, None, 'admin.edit', target.username)
        messages.success(request, 'Admin saved.')
        return redirect('dashboard:admins')
    return render(request, 'dashboard/admin_form.html', {'form': form, 'target': target, 'creating': False})


@superuser_required
def admin_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(target, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        log(request.user, None, 'admin.password', target.username)
        messages.success(request, f'Password updated for "{target.username}".')
        return redirect('dashboard:admins')
    return render(request, 'dashboard/admin_password.html', {'form': form, 'target': target})


@require_POST
@superuser_required
def admin_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('dashboard:admins')
    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])
    log(request.user, None, 'admin.activate' if target.is_active else 'admin.deactivate', target.username)
    messages.success(request, f'"{target.username}" {"reactivated" if target.is_active else "deactivated"}.')
    return redirect('dashboard:admins')


# ---------------------------------------------------------------- week editor

@space_admin_required
def space_current(request, space):
    return redirect('dashboard:week', slug=space.slug, week=current_week_start().isoformat())


@space_admin_required
def week_editor(request, space, week):
    start = _week_start(week)
    if start.isoformat() != week:
        return redirect('dashboard:week', slug=space.slug, week=start.isoformat())
    wk = Week.objects.filter(space=space, start=start).select_related('copied_from').first()
    timeslots = list(space.timeslots.all())
    if wk:
        sessions = list(week_sessions(wk))
        removed = list(removed_sessions(wk)) if wk.copied_from_id else []
    else:
        sessions, removed = [], []
    display_week = wk or Week(space=space, start=start)
    rows = build_grid(display_week, timeslots, sessions)
    for row in rows:
        row['slots'] = list(zip(timeslots, row['cells']))

    copy_form = CopyWeekForm(space=space, start=start, target_has_sessions=bool(sessions))
    try:
        notes_url = reverse('notes:list', args=[space.slug]) + '?' + urlencode({'week': start.isoformat()})
    except NoReverseMatch:
        notes_url = None

    return render(request, 'dashboard/week.html', {
        'space': space,
        'week': wk,
        'start': start,
        'end': start + timedelta(days=5),
        'is_published': bool(wk and wk.is_published),
        'rows': rows,
        'timeslots': timeslots,
        'has_sessions': bool(sessions),
        'session_count': len(sessions),
        'removed': removed,
        'copy_form': copy_form,
        'has_other_weeks': bool(copy_form.fields['source'].queryset),
        'prev': (start - timedelta(days=7)).isoformat(),
        'next': (start + timedelta(days=7)).isoformat(),
        'this_week': current_week_start().isoformat(),
        'is_this_week': start == current_week_start(),
        'notes_url': notes_url,
    })


@require_POST
@space_admin_required
def week_publish(request, space, week):
    start = _week_start(week)
    wk, _ = Week.objects.get_or_create(space=space, start=start)
    publish = request.POST.get('action') != 'unpublish'
    wk.status = Week.PUBLISHED if publish else Week.DRAFT
    wk.save()
    log(request.user, space, 'week.publish' if publish else 'week.unpublish', f'{start:%Y-%m-%d}')
    messages.success(request, 'Week published.' if publish else 'Week moved back to draft.')
    return redirect(_week_url(space, start))


@require_POST
@space_admin_required
def week_start_blank(request, space, week):
    start = _week_start(week)
    wk, created = Week.objects.get_or_create(space=space, start=start)
    if created:
        log(request.user, space, 'week.create', f'{start:%Y-%m-%d} (blank)')
    return redirect(_week_url(space, start))


@require_POST
@space_admin_required
def week_copy(request, space, week):
    start = _week_start(week)
    existing = Week.objects.filter(space=space, start=start).first()
    has_sessions = bool(existing and existing.sessions.exists())
    form = CopyWeekForm(request.POST, space=space, start=start, target_has_sessions=has_sessions)
    if not form.is_valid():
        messages.error(request, f'Nothing copied: {_form_errors(form)}')
        return redirect(_week_url(space, start))
    source = form.cleaned_data['source']
    replace = form.cleaned_data['mode'] != CopyWeekForm.MERGE
    with transaction.atomic():
        target, _ = Week.objects.get_or_create(space=space, start=start)
        n = copy_week(source, target, replace=replace,
                      include_notes=form.cleaned_data['include_notes'])
    log(request.user, space, 'week.copy',
        f'{source.start:%Y-%m-%d} -> {start:%Y-%m-%d} ({"replace" if replace else "merge"}, {n} sessions)')
    messages.success(request, f'Copied {n} session{"s" if n != 1 else ""} from the week of {source.start:%d %b}.')
    return redirect(_week_url(space, start))


# ---------------------------------------------------------------- sessions

def _render_session_form(request, space, form, *, start, session=None):
    ctx = {
        'space': space, 'form': form, 'session': session, 'start': start,
        'back_url': _week_url(space, start),
        'action_url': request.path,
    }
    template = 'dashboard/_session_form.html' if request.GET.get('partial') else 'dashboard/session_form.html'
    return render(request, template, ctx)


@space_admin_required
def session_create(request, space, week):
    start = _week_start(week)
    if request.method == 'POST':
        form = SessionForm(request.POST, space=space)
        if form.is_valid():
            with transaction.atomic():
                wk, _ = Week.objects.get_or_create(space=space, start=start)
                form.instance.week = wk
                session = form.save()
                _touch(wk)
            log(request.user, space, 'session.create', f'{start:%Y-%m-%d} {session}')
            messages.success(request, 'Session added.')
            return redirect(_week_url(space, start))
    else:
        initial = {}
        day = request.GET.get('day', '')
        if day.isdigit() and int(day) in dict(DAY_CHOICES):
            initial['day'] = int(day)
        slot = request.GET.get('slot', '')
        if slot.isdigit() and space.timeslots.filter(pk=slot).exists():
            initial['timeslot'] = int(slot)
        form = SessionForm(initial=initial, space=space)
    return _render_session_form(request, space, form, start=start)


@space_admin_required
def session_edit(request, space, pk):
    session = _space_session(space, pk)
    start = session.week.start
    form = SessionForm(request.POST or None, instance=session, space=space)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            session = form.save()
            _touch(session.week)
        log(request.user, space, 'session.edit', f'{start:%Y-%m-%d} {session}')
        messages.success(request, 'Session saved.')
        return redirect(_week_url(space, start))
    return _render_session_form(request, space, form, start=start, session=session)


@require_POST
@space_admin_required
def session_delete(request, space, pk):
    session = _space_session(space, pk)
    week, label = session.week, str(session)
    session.delete()
    _touch(week)
    log(request.user, space, 'session.delete', f'{week.start:%Y-%m-%d} {label}')
    messages.success(request, 'Session deleted.')
    return redirect(_week_url(space, week.start))


@require_POST
@space_admin_required
def session_toggle_cancel(request, space, pk):
    session = _space_session(space, pk)
    session.is_cancelled = not session.is_cancelled
    session.save(update_fields=['is_cancelled'])
    _touch(session.week)
    log(request.user, space, 'session.cancel' if session.is_cancelled else 'session.restore',
        f'{session.week.start:%Y-%m-%d} {session}')
    messages.success(request, 'Session cancelled.' if session.is_cancelled else 'Session restored.')
    return redirect(_week_url(space, session.week.start))

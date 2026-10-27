"""Dashboard views for space notes (Editor.js based)."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Note, Week
from .notes_render import ContentError, clean_content, content_to_text, text_to_content
from .services import log, parse_week, space_admin_required

TITLE_MAX = Note._meta.get_field('title').max_length


def _week_param(request):
    """?week=YYYY-MM-DD snapped to its Saturday, or None."""
    value = request.GET.get('week', '')
    if not value:
        return None
    try:
        return parse_week(value)
    except ValueError:
        return None


def _list_url(space, week_start=None):
    url = reverse('notes:list', args=[space.slug])
    return f'{url}?week={week_start.isoformat()}' if week_start else url


@space_admin_required
def note_list(request, space):
    week_start = _week_param(request)
    notes = Note.objects.filter(space=space).select_related('week', 'author')
    if week_start:
        notes = notes.filter(week__isnull=True) | notes.filter(week__start=week_start)
    notes = list(notes)

    space_wide = [n for n in notes if n.week_id is None]
    groups, by_week = [], {}
    for n in sorted((n for n in notes if n.week_id), key=lambda n: n.week.start, reverse=True):
        if n.week_id not in by_week:
            by_week[n.week_id] = {'week': n.week, 'notes': []}
            groups.append(by_week[n.week_id])
        by_week[n.week_id]['notes'].append(n)

    return render(request, 'notes/list.html', {
        'space': space,
        'week_start': week_start,
        'space_wide': space_wide,
        'week_groups': groups,
        'has_notes': bool(notes),
        'create_url': reverse('notes:create', args=[space.slug])
                      + (f'?week={week_start.isoformat()}' if week_start else ''),
    })


def _scope_choices(space, selected_start=None):
    starts = list(space.weeks.order_by('-start').values_list('start', flat=True))
    if selected_start and selected_start not in starts:
        starts.append(selected_start)
        starts.sort(reverse=True)
    return starts


def _editor(request, space, note=None):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        scope = request.POST.get('scope', '').strip()
        pinned = request.POST.get('pinned') == 'on'
        errors = {}

        if len(title) > TITLE_MAX:
            errors['title'] = f'Keep the title under {TITLE_MAX} characters.'

        week_start = None
        if scope:
            try:
                week_start = parse_week(scope)
            except ValueError:
                errors['scope'] = 'Choose a valid week.'

        raw_json = request.POST.get('content', '').strip()
        try:
            if raw_json:
                content = clean_content(raw_json)
            else:
                content = text_to_content(request.POST.get('content_text', ''))
        except ContentError as e:
            errors['content'] = str(e)
            content = note.content if note else {'blocks': []}

        if not errors:
            with transaction.atomic():
                week = None
                if week_start:
                    week, _ = Week.objects.get_or_create(
                        space=space, start=week_start, defaults={'status': Week.DRAFT})
                creating = note is None
                if creating:
                    note = Note(space=space, author=request.user)
                note.title, note.week, note.pinned, note.content = title, week, pinned, content
                note.save()
                scope_label = f'week of {week.start:%d %b %Y}' if week else 'whole space'
                log(request.user, space, 'note_create' if creating else 'note_edit',
                    f'"{note}" ({scope_label})')
            messages.success(request, 'Note created.' if creating else 'Note saved.')
            if request.POST.get('continue') == '1':
                return redirect('notes:edit', space.slug, note.pk)
            return redirect(_list_url(space, week_start))

        form = {'title': title, 'scope': scope, 'pinned': pinned}
        initial_content = content
        selected = week_start
    else:
        if note:
            selected = note.week.start if note.week_id else None
            form = {'title': note.title, 'scope': selected.isoformat() if selected else '',
                    'pinned': note.pinned}
            initial_content = note.content or {'blocks': []}
        else:
            selected = _week_param(request)
            form = {'title': '', 'scope': selected.isoformat() if selected else '', 'pinned': False}
            initial_content = {'blocks': []}
        errors = {}

    week_starts = _scope_choices(space, selected)
    existing = set(space.weeks.values_list('start', flat=True))
    return render(request, 'notes/form.html', {
        'space': space,
        'note': note,
        'form': form,
        'errors': errors,
        'scope_options': [
            {'value': s.isoformat(), 'label': f'Week of {s:%d %b %Y}', 'new': s not in existing}
            for s in week_starts
        ],
        'initial_content': initial_content,
        'initial_text': content_to_text(initial_content),
        'back_url': _list_url(space, selected),
    }, status=400 if errors else 200)


@space_admin_required
@require_http_methods(['GET', 'POST'])
def note_create(request, space):
    return _editor(request, space)


@space_admin_required
@require_http_methods(['GET', 'POST'])
def note_edit(request, space, pk):
    note = get_object_or_404(Note.objects.select_related('week'), pk=pk, space=space)
    return _editor(request, space, note)


@space_admin_required
@require_http_methods(['GET', 'POST'])
def note_delete(request, space, pk):
    note = get_object_or_404(Note.objects.select_related('week'), pk=pk, space=space)
    week_start = note.week.start if note.week_id else None
    if request.method == 'POST':
        label = str(note)
        note.delete()
        log(request.user, space, 'note_delete', f'"{label}"')
        messages.success(request, 'Note deleted.')
        return redirect(_list_url(space, week_start))
    return render(request, 'notes/confirm_delete.html', {
        'space': space, 'note': note, 'back_url': _list_url(space, week_start),
    })

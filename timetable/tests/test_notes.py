import json
from datetime import date

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from timetable.models import AuditLog, Note, Space, SpaceMembership, Week
from timetable.notes_render import (
    MAX_BLOCKS, ContentError, clean_content, render_blocks, sanitize_inline, text_to_content,
)

User = get_user_model()
SAT = date(2026, 10, 24)  # a Saturday


def doc(*blocks):
    return {'blocks': list(blocks)}


class RenderTests(TestCase):
    def r(self, *blocks, **kw):
        return str(render_blocks(doc(*blocks), **kw))

    def test_paragraph(self):
        self.assertEqual(self.r({'type': 'paragraph', 'data': {'text': 'Hi <b>there</b>'}}),
                         '<p>Hi <b>there</b></p>')

    def test_empty_paragraph_skipped(self):
        self.assertEqual(self.r({'type': 'paragraph', 'data': {'text': ''}}), '')

    def test_header_levels(self):
        out = self.r({'type': 'header', 'data': {'text': 'A', 'level': 2}},
                     {'type': 'header', 'data': {'text': 'B', 'level': 3}})
        self.assertIn('<h3 class="note-heading">A</h3>', out)
        self.assertIn('<h4 class="note-heading">B</h4>', out)
        out = self.r({'type': 'header', 'data': {'text': 'A', 'level': 2}}, top_level=4)
        self.assertIn('<h4', out)

    def test_legacy_list(self):
        out = self.r({'type': 'list', 'data': {'style': 'ordered', 'items': ['one', '<i>two</i>']}})
        self.assertEqual(out, '<ol><li>one</li><li><i>two</i></li></ol>')

    def test_nested_list_v2(self):
        out = self.r({'type': 'list', 'data': {'style': 'unordered', 'meta': {}, 'items': [
            {'content': 'a', 'meta': {}, 'items': [{'content': 'a1', 'meta': {}, 'items': []}]},
            {'content': 'b', 'meta': {}, 'items': []},
        ]}})
        self.assertEqual(out, '<ul><li>a<ul><li>a1</li></ul></li><li>b</li></ul>')

    def test_list_v2_checklist_style(self):
        out = self.r({'type': 'list', 'data': {'style': 'checklist', 'meta': {}, 'items': [
            {'content': 'x', 'meta': {'checked': True}, 'items': []}]}})
        self.assertIn('note-check is-checked', out)
        self.assertIn('(done)', out)

    def test_checklist(self):
        out = self.r({'type': 'checklist', 'data': {'items': [
            {'text': 'Laptop', 'checked': False}, {'text': 'JDK', 'checked': True}]}})
        self.assertIn('aria-hidden="true"', out)
        self.assertIn('Laptop</span><span class="visually-hidden"> (not done)</span>', out)
        self.assertIn('JDK</span><span class="visually-hidden"> (done)</span>', out)

    def test_quote_delimiter_code(self):
        out = self.r({'type': 'quote', 'data': {'text': 'Q', 'caption': 'C'}},
                     {'type': 'delimiter', 'data': {}},
                     {'type': 'code', 'data': {'code': '<b>x</b> & y'}})
        self.assertIn('<blockquote>Q</blockquote><figcaption>C</figcaption>', out)
        self.assertIn('<hr class="note-delimiter">', out)
        self.assertIn('<code>&lt;b&gt;x&lt;/b&gt; &amp; y</code>', out)

    def test_unknown_and_garbage(self):
        self.assertEqual(self.r({'type': 'raw', 'data': {'html': '<script>x</script>'}}, 'junk', None), '')
        self.assertEqual(str(render_blocks(None)), '')
        self.assertEqual(str(render_blocks('not json')), '')
        self.assertEqual(str(render_blocks({'blocks': 'x'})), '')

    def test_deep_nesting_is_bounded(self):
        item = {'content': 'leaf', 'meta': {}, 'items': []}
        for _ in range(50):
            item = {'content': 'n', 'meta': {}, 'items': [item]}
        out = self.r({'type': 'list', 'data': {'style': 'unordered', 'items': [item]}})
        self.assertNotIn('leaf', out)


class SanitizerTests(TestCase):
    def assertNoActiveContent(self, html):
        low = html.lower()
        for bad in ('<script', '<img', 'onerror', 'onclick', 'javascript:', '<svg', '<iframe', 'style='):
            self.assertNotIn(bad, low)

    def test_script_removed(self):
        self.assertEqual(sanitize_inline('<script>alert(1)</script>ok'), 'ok')

    def test_img_onerror(self):
        self.assertEqual(sanitize_inline('<img src=x onerror=alert(1)>'), '')

    def test_attributes_stripped(self):
        self.assertEqual(sanitize_inline('<b onclick="x" style="y">b</b>'), '<b>b</b>')

    def test_javascript_hrefs(self):
        for href in ('javascript:alert(1)', ' javascript:alert(1)', 'JaVaScRiPt:alert(1)',
                     'jav&#x09;ascript:alert(1)', '&#106;avascript:alert(1)', 'java\nscript:x',
                     'data:text/html,<script>x</script>', 'vbscript:x', '//evil.com', '/relative'):
            out = sanitize_inline(f'<a href="{href}">x</a>')
            self.assertEqual(out, '<a>x</a>', href)

    def test_safe_hrefs(self):
        out = sanitize_inline('<a href="https://usthb.dz/?a=1&b=2" title="t">x</a>')
        self.assertEqual(out, '<a href="https://usthb.dz/?a=1&amp;b=2" rel="noopener nofollow" target="_blank">x</a>')
        self.assertIn('href="mailto:a@b.dz"', sanitize_inline('<a href="mailto:a@b.dz">m</a>'))

    def test_href_attribute_breakout(self):
        out = sanitize_inline('<a href="https://x.dz/&quot; onmouseover=&quot;alert(1)">x</a>')
        self.assertNotIn('" onmouseover', out)
        self.assertIn('&quot;', out)

    def test_entities_stay_escaped(self):
        self.assertEqual(sanitize_inline('&lt;script&gt;alert(1)&lt;/script&gt;'),
                         '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_unclosed_and_malformed(self):
        self.assertEqual(sanitize_inline('<b>bold <i>it'), '<b>bold <i>it</i></b>')
        self.assertEqual(sanitize_inline('</b>x</i>'), 'x')
        self.assertNoActiveContent(sanitize_inline('<scr<script>ipt>alert(1)</script>'))
        self.assertNoActiveContent(sanitize_inline('<img src=x onerror=alert(1)'))
        self.assertNoActiveContent(sanitize_inline('<svg><script>alert(1)</script></svg>'))
        self.assertNoActiveContent(sanitize_inline('<!--<script>-->x<style>a{}</style>'))
        self.assertEqual(sanitize_inline('x < y'), 'x &lt; y')

    def test_allowed_tags(self):
        html = '<strong>a</strong><em>b</em><u>c</u><s>d</s><code class="inline-code">e</code><mark class="cdx-marker">f</mark>g<br>h'
        self.assertEqual(sanitize_inline(html),
                         '<strong>a</strong><em>b</em><u>c</u><s>d</s><code>e</code><mark>f</mark>g<br>h')

    def test_xss_through_every_block(self):
        evil = '<img src=x onerror=alert(1)><a href="javascript:alert(1)">x</a><script>alert(1)</script>'
        out = str(render_blocks(doc(
            {'type': 'paragraph', 'data': {'text': evil}},
            {'type': 'header', 'data': {'text': evil, 'level': 2}},
            {'type': 'list', 'data': {'style': 'unordered', 'items': [evil, {'content': evil, 'items': []}]}},
            {'type': 'checklist', 'data': {'items': [{'text': evil, 'checked': True}]}},
            {'type': 'quote', 'data': {'text': evil, 'caption': evil}},
        )))
        self.assertNoActiveContent(out)
        code = str(render_blocks(doc({'type': 'code', 'data': {'code': evil}})))
        self.assertNotIn('<img', code)
        self.assertNotIn('<script', code)
        self.assertIn('&lt;script&gt;', code)


class ValidationTests(TestCase):
    def test_requires_object_with_blocks(self):
        for raw in ('', 'nope', '[]', '{"blocks": "x"}', '{}', '42'):
            with self.assertRaises(ContentError):
                clean_content(raw)

    def test_max_blocks(self):
        blocks = [{'type': 'delimiter', 'data': {}}] * (MAX_BLOCKS + 1)
        with self.assertRaises(ContentError):
            clean_content(json.dumps({'blocks': blocks}))
        clean_content(json.dumps({'blocks': blocks[:MAX_BLOCKS]}))

    def test_max_size(self):
        raw = json.dumps({'blocks': [{'type': 'paragraph', 'data': {'text': 'x' * 110_000}}]})
        with self.assertRaises(ContentError):
            clean_content(raw)

    def test_whitelist(self):
        raw = json.dumps({'time': 1, 'version': '2.31.7', 'evil': 1, 'blocks': [
            {'id': 'abc', 'type': 'paragraph', 'data': {'text': '<b onclick=x>a</b>', 'extra': 1}, 'tunes': {}},
            {'type': 'raw', 'data': {'html': '<script></script>'}},
            {'type': 'header', 'data': {'text': 'h', 'level': 1}},
            {'type': 'list', 'data': {'style': 'weird', 'items': ['s', {'content': 'c', 'items': [], 'meta': {'checked': True, 'x': 1}}]}},
            {'type': 'checklist', 'data': {'items': [{'text': 't', 'checked': 'yes', 'x': 1}]}},
            {'id': '<bad id>', 'type': 'delimiter', 'data': {'x': 1}},
        ]})
        out = clean_content(raw)
        self.assertEqual(set(out), {'time', 'version', 'blocks'})
        b = out['blocks']
        self.assertEqual(len(b), 5)
        self.assertEqual(b[0], {'id': 'abc', 'type': 'paragraph', 'data': {'text': '<b>a</b>'}})
        self.assertEqual(b[1]['data'], {'text': 'h', 'level': 2})
        self.assertEqual(b[2]['data']['style'], 'unordered')
        self.assertEqual(b[2]['data']['items'][1], {'content': 'c', 'meta': {'checked': True}, 'items': []})
        self.assertEqual(b[3]['data'], {'items': [{'text': 't', 'checked': False}]})
        self.assertEqual(b[4], {'type': 'delimiter', 'data': {}})

    def test_text_fallback(self):
        out = text_to_content('Hello <b>\n\n\nSecond\nline')
        self.assertEqual(out['blocks'], [
            {'type': 'paragraph', 'data': {'text': 'Hello &lt;b&gt;'}},
            {'type': 'paragraph', 'data': {'text': 'Second<br>line'}},
        ])


class NoteViewTests(TestCase):
    def setUp(self):
        self.space = Space.objects.create(name='MCIL B', slug='mcil-b')
        self.other = Space.objects.create(name='Other', slug='other')
        self.admin = User.objects.create_user('admin', password='pw')
        SpaceMembership.objects.create(space=self.space, user=self.admin)
        self.outsider = User.objects.create_user('outsider', password='pw')
        self.week = Week.objects.create(space=self.space, start=SAT)
        self.note = Note.objects.create(space=self.space, week=self.week, title='Old',
                                        content=doc({'type': 'paragraph', 'data': {'text': 'x'}}))
        self.foreign = Note.objects.create(space=self.other, title='Theirs')
        self.client.force_login(self.admin)

    def url(self, name, *args):
        return reverse(f'notes:{name}', args=[self.space.slug, *args])

    def payload(self, text='Hello'):
        return json.dumps({'blocks': [{'type': 'paragraph', 'data': {'text': text}}]})

    def test_anonymous_redirects_to_login(self):
        self.client.logout()
        for url in (self.url('list'), self.url('create'), self.url('edit', self.note.pk),
                    self.url('delete', self.note.pk)):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn(reverse('login'), resp['Location'])

    def test_non_member_forbidden(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url('list')).status_code, 403)
        self.assertEqual(self.client.post(self.url('delete', self.note.pk)).status_code, 403)
        self.assertTrue(Note.objects.filter(pk=self.note.pk).exists())

    def test_cross_space_pk_404(self):
        self.assertEqual(self.client.get(self.url('edit', self.foreign.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('delete', self.foreign.pk)).status_code, 404)
        self.assertTrue(Note.objects.filter(pk=self.foreign.pk).exists())

    def test_list(self):
        Note.objects.create(space=self.space, title='Pinned one', pinned=True)
        resp = self.client.get(self.url('list'))
        self.assertContains(resp, 'Pinned one')
        self.assertContains(resp, 'Old')
        self.assertNotContains(resp, 'Theirs')
        resp = self.client.get(self.url('list') + '?week=2026-10-31')
        self.assertContains(resp, 'Pinned one')
        self.assertNotContains(resp, '>Old<')
        self.assertContains(resp, '?week=2026-10-31')

    def test_create_space_wide(self):
        resp = self.client.post(self.url('create'), {
            'title': 'Exam info', 'scope': '', 'pinned': 'on', 'content': self.payload('<b>Room</b>')})
        note = Note.objects.get(title='Exam info')
        self.assertRedirects(resp, self.url('list'), fetch_redirect_response=False)
        self.assertIsNone(note.week)
        self.assertTrue(note.pinned)
        self.assertEqual(note.author, self.admin)
        self.assertEqual(note.content['blocks'][0]['data']['text'], '<b>Room</b>')
        self.assertTrue(AuditLog.objects.filter(action='note_create', space=self.space).exists())

    def test_create_for_new_week_makes_draft_week(self):
        self.client.post(self.url('create'), {'title': 'Next', 'scope': '2026-11-04',
                                              'content': self.payload()})
        week = Week.objects.get(space=self.space, start=date(2026, 10, 31))
        self.assertEqual(week.status, Week.DRAFT)
        self.assertEqual(Note.objects.get(title='Next').week, week)

    def test_create_fallback_text(self):
        self.client.post(self.url('create'), {'title': 'Plain', 'content': '',
                                              'content_text': 'one\n\ntwo'})
        self.assertEqual(len(Note.objects.get(title='Plain').content['blocks']), 2)

    def test_create_invalid_content(self):
        resp = self.client.post(self.url('create'), {'title': 'Bad', 'content': '[1,2]'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Note.objects.filter(title='Bad').exists())

    def test_week_preselect(self):
        resp = self.client.get(self.url('create') + '?week=2026-10-27')
        self.assertContains(resp, '<option value="2026-10-24" selected>')
        resp = self.client.get(self.url('create') + '?week=2026-11-07')
        self.assertContains(resp, '<option value="2026-11-07" selected>Week of 07 Nov 2026 (new draft week)')

    def test_edit(self):
        resp = self.client.get(self.url('edit', self.note.pk))
        self.assertContains(resp, 'value="Old"')
        self.assertContains(resp, 'id="note-initial"')
        self.assertContains(resp, 'cdn.jsdelivr.net/npm/@editorjs/editorjs@2.31.7')
        resp = self.client.post(self.url('edit', self.note.pk), {
            'title': 'New', 'scope': '', 'content': self.payload('Edited'), 'continue': '1'})
        self.assertRedirects(resp, self.url('edit', self.note.pk), fetch_redirect_response=False)
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'New')
        self.assertIsNone(self.note.week)
        self.assertEqual(self.note.author, None)  # author not overwritten on edit
        self.assertTrue(AuditLog.objects.filter(action='note_edit').exists())

    def test_delete(self):
        resp = self.client.get(self.url('delete', self.note.pk))
        self.assertContains(resp, 'Delete note?')
        self.assertTrue(Note.objects.filter(pk=self.note.pk).exists())
        resp = self.client.post(self.url('delete', self.note.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Note.objects.filter(pk=self.note.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action='note_delete').exists())


class PublicPartialTests(TestCase):
    def setUp(self):
        self.space = Space.objects.create(name='S', slug='s')
        self.week = Week.objects.create(space=self.space, start=SAT)

    def test_renders_pinned_and_week_notes(self):
        pinned = Note.objects.create(space=self.space, pinned=True, title='Welcome',
                                     content=doc({'type': 'header', 'data': {'text': 'Sub', 'level': 2}}))
        weekly = Note.objects.create(space=self.space, week=self.week, title='This week',
                                     content=doc({'type': 'paragraph', 'data': {'text': '<script>x</script>TP'}}))
        html = render_to_string('notes/_public_notes.html',
                                {'pinned_notes': [pinned], 'week_notes': Note.objects.filter(pk=weekly.pk)})
        self.assertIn('<h2 id="notes-heading">Notes</h2>', html)
        self.assertIn('Pinned</span>', html)
        self.assertIn('<h3 class="note-title">Welcome</h3>', html)
        self.assertIn('<h4 class="note-heading">Sub</h4>', html)
        self.assertIn('<p>TP</p>', html)
        self.assertNotIn('<script>x', html)
        self.assertIn('css/notes.css', html)
        self.assertIn('Updated', html)
        self.assertLess(html.index('Welcome'), html.index('This week'))

    def test_hidden_when_empty(self):
        html = render_to_string('notes/_public_notes.html',
                                {'pinned_notes': Note.objects.none(), 'week_notes': []})
        self.assertEqual(html.strip(), '')

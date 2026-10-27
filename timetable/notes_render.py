"""Editor.js JSON -> safe HTML, plus validation of submitted editor payloads.

SECURITY BOUNDARY: every piece of user text that reaches HTML goes through
`sanitize_inline` (whitelist built on html.parser) or `html.escape`. Nothing
from the stored JSON is ever marked safe without passing through one of them.
"""

import json
import re
from html import escape
from html.parser import HTMLParser

from django.utils.safestring import SafeString, mark_safe

MAX_BLOCKS = 200
MAX_BYTES = 100 * 1024
MAX_DEPTH = 8          # nested list depth
MAX_TEXT = 20_000      # per text field, after sanitizing

ALLOWED_INLINE = {'b', 'strong', 'i', 'em', 'u', 's', 'code', 'mark', 'br', 'a'}
VOID_TAGS = {'br'}
DROP_CONTENT = {'script', 'style', 'template', 'noscript', 'iframe', 'object', 'textarea', 'title'}
SAFE_SCHEMES = ('http:', 'https:', 'mailto:')
# Whitespace and C0/C1 controls: browsers ignore them inside URL schemes ("jav\tascript:").
_URL_JUNK = re.compile(r'[\x00-\x20\x7f-\x9f   -‏    　﻿]+')


def safe_href(value):
    """Return the href if its scheme is http/https/mailto, else None."""
    if not value:
        return None
    url = value.strip()
    if re.search(r'[\x00-\x1f\x7f]', url):
        return None  # control characters anywhere: refuse rather than guess
    if not _URL_JUNK.sub('', url).lower().startswith(SAFE_SCHEMES):
        return None
    return url


class _InlineSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.drop_depth = 0

    # Tags -------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.drop_depth += 1
            return
        if self.drop_depth or tag not in ALLOWED_INLINE:
            return
        if tag in VOID_TAGS:
            self.out.append('<br>')
            return
        if tag == 'a':
            href = safe_href(dict(attrs).get('href'))
            if href:
                self.out.append(f'<a href="{escape(href, quote=True)}" rel="noopener nofollow" target="_blank">')
            else:
                self.out.append('<a>')
        else:
            self.out.append(f'<{tag}>')
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID_TAGS and not self.drop_depth:
            self.out.append('<br>')

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f'</{t}>')
            if t == tag:
                break

    # Text ---------------------------------------------------------------
    def handle_data(self, data):
        if not self.drop_depth:
            self.out.append(escape(data, quote=False))

    # Comments, doctypes, processing instructions, CDATA: dropped.
    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass

    def result(self):
        self.close()
        while self.stack:
            self.out.append(f'</{self.stack.pop()}>')
        return ''.join(self.out)


def sanitize_inline(text) -> str:
    """Whitelist-sanitize inline HTML. Returns an HTML string safe to embed."""
    if not isinstance(text, str) or not text:
        return ''
    parser = _InlineSanitizer()
    parser.feed(text)
    return parser.result()


# ---------------------------------------------------------------- rendering

def _list_items_html(items, ordered, checklist, depth):
    if depth > MAX_DEPTH or not isinstance(items, list):
        return ''
    tag = 'ol' if ordered else 'ul'
    cls = ' class="note-checklist"' if checklist else ''
    parts = []
    for item in items:
        children = ''
        checked = False
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get('content', item.get('text', ''))
            meta = item.get('meta') if isinstance(item.get('meta'), dict) else {}
            checked = meta.get('checked') is True or item.get('checked') is True
            children = _list_items_html(item.get('items') or [], ordered, checklist, depth + 1)
        else:
            continue
        body = sanitize_inline(text)
        if checklist:
            body = _check_html(body, checked)
        parts.append(f'<li>{body}{children}</li>')
    if not parts:
        return ''
    return f'<{tag}{cls}>{"".join(parts)}</{tag}>'


def _check_html(body_html, checked):
    state = 'done' if checked else 'not done'
    mark = ' is-checked' if checked else ''
    return (f'<span class="note-check{mark}" aria-hidden="true"></span>'
            f'<span class="note-check-text">{body_html}</span>'
            f'<span class="visually-hidden"> ({state})</span>')


def _render_block(block, top_level):
    if not isinstance(block, dict):
        return ''
    kind = block.get('type')
    data = block.get('data') if isinstance(block.get('data'), dict) else {}

    if kind == 'paragraph':
        text = sanitize_inline(data.get('text', ''))
        return f'<p>{text}</p>' if text.strip() else ''
    if kind == 'header':
        try:
            level = int(data.get('level', 2))
        except (TypeError, ValueError):
            level = 2
        h = top_level if level <= 2 else top_level + 1
        h = max(1, min(h, 6))
        return f'<h{h} class="note-heading">{sanitize_inline(data.get("text", ""))}</h{h}>'
    if kind == 'list':
        style = data.get('style')
        return _list_items_html(data.get('items'), style == 'ordered', style == 'checklist', 0)
    if kind == 'checklist':
        items = data.get('items') if isinstance(data.get('items'), list) else []
        lis = []
        for item in items:
            if isinstance(item, dict):
                lis.append('<li>' + _check_html(sanitize_inline(item.get('text', '')),
                                                item.get('checked') is True) + '</li>')
        return f'<ul class="note-checklist">{"".join(lis)}</ul>' if lis else ''
    if kind == 'quote':
        text = sanitize_inline(data.get('text', ''))
        caption = sanitize_inline(data.get('caption', ''))
        cap = f'<figcaption>{caption}</figcaption>' if caption.strip() else ''
        return f'<figure class="note-quote"><blockquote>{text}</blockquote>{cap}</figure>'
    if kind == 'delimiter':
        return '<hr class="note-delimiter">'
    if kind == 'code':
        code = data.get('code', '')
        if not isinstance(code, str):
            return ''
        return f'<pre class="note-code"><code>{escape(code, quote=False)}</code></pre>'
    return ''


def render_blocks(content, top_level=3) -> SafeString:
    """Convert Editor.js output to HTML. Header level 2 -> h{top_level}, 3+ -> h{top_level+1}."""
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return mark_safe('')
    if not isinstance(content, dict) or not isinstance(content.get('blocks'), list):
        return mark_safe('')
    html = ''.join(_render_block(b, top_level) for b in content['blocks'][:MAX_BLOCKS])
    return mark_safe(html)  # every fragment above is escaped or sanitized


# ---------------------------------------------------------------- validation

class ContentError(ValueError):
    pass


def _clean_text(value):
    if not isinstance(value, str):
        return ''
    return sanitize_inline(value)[:MAX_TEXT]


def _clean_list_items(items, depth=0):
    if not isinstance(items, list) or depth > MAX_DEPTH:
        return []
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(_clean_text(item))
        elif isinstance(item, dict):
            meta_in = item.get('meta') if isinstance(item.get('meta'), dict) else {}
            meta = {}
            if isinstance(meta_in.get('checked'), bool):
                meta['checked'] = meta_in['checked']
            out.append({
                'content': _clean_text(item.get('content', '')),
                'meta': meta,
                'items': _clean_list_items(item.get('items'), depth + 1),
            })
    return out


def _clean_block(block):
    if not isinstance(block, dict):
        return None
    kind = block.get('type')
    data = block.get('data') if isinstance(block.get('data'), dict) else {}
    if kind == 'paragraph':
        clean = {'text': _clean_text(data.get('text'))}
    elif kind == 'header':
        level = data.get('level')
        clean = {'text': _clean_text(data.get('text')), 'level': 3 if level == 3 else 2}
    elif kind == 'list':
        style = data.get('style') if data.get('style') in ('ordered', 'unordered', 'checklist') else 'unordered'
        clean = {'style': style, 'meta': {}, 'items': _clean_list_items(data.get('items'))}
        meta_in = data.get('meta') if isinstance(data.get('meta'), dict) else {}
        start = meta_in.get('start')
        if style == 'ordered' and isinstance(start, int) and not isinstance(start, bool) and 0 < start < 10_000:
            clean['meta']['start'] = start
        if meta_in.get('counterType') in ('numeric', 'lower-roman', 'upper-roman', 'lower-alpha', 'upper-alpha'):
            clean['meta']['counterType'] = meta_in['counterType']
    elif kind == 'checklist':
        items = data.get('items') if isinstance(data.get('items'), list) else []
        clean = {'items': [{'text': _clean_text(i.get('text')), 'checked': i.get('checked') is True}
                           for i in items if isinstance(i, dict)]}
    elif kind == 'quote':
        clean = {'text': _clean_text(data.get('text')), 'caption': _clean_text(data.get('caption')),
                 'alignment': 'center' if data.get('alignment') == 'center' else 'left'}
    elif kind == 'delimiter':
        clean = {}
    elif kind == 'code':
        code = data.get('code')
        clean = {'code': code[:MAX_TEXT] if isinstance(code, str) else ''}
    else:
        return None
    out = {'type': kind, 'data': clean}
    bid = block.get('id')
    if isinstance(bid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,40}', bid):
        out['id'] = bid
    return out


def clean_content(raw) -> dict:
    """Validate a submitted Editor.js payload (JSON string). Raises ContentError."""
    if not isinstance(raw, str):
        raise ContentError('Invalid note content.')
    if len(raw.encode('utf-8')) > MAX_BYTES:
        raise ContentError('The note is too long (max 100 KB).')
    try:
        data = json.loads(raw)
    except ValueError:
        raise ContentError('Invalid note content.')
    if not isinstance(data, dict) or not isinstance(data.get('blocks'), list):
        raise ContentError('Invalid note content.')
    if len(data['blocks']) > MAX_BLOCKS:
        raise ContentError(f'The note has too many blocks (max {MAX_BLOCKS}).')
    blocks = [b for b in (_clean_block(b) for b in data['blocks']) if b is not None]
    out = {'blocks': blocks}
    if isinstance(data.get('time'), int) and not isinstance(data.get('time'), bool):
        out['time'] = data['time']
    if isinstance(data.get('version'), str) and len(data['version']) <= 20:
        out['version'] = data['version']
    return out


def text_to_content(text) -> dict:
    """Plain-text fallback: blank-line separated paragraphs."""
    if not isinstance(text, str):
        text = ''
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ContentError('The note is too long (max 100 KB).')
    paras = [p.strip() for p in re.split(r'\r?\n\s*\r?\n', text) if p.strip()]
    if len(paras) > MAX_BLOCKS:
        raise ContentError(f'The note has too many blocks (max {MAX_BLOCKS}).')
    return {'blocks': [
        {'type': 'paragraph', 'data': {'text': escape(p, quote=False).replace('\r\n', '\n').replace('\n', '<br>')}}
        for p in paras
    ]}


def content_to_text(content) -> str:
    """Rough plain text of a note, used to prefill the no-JS textarea."""
    if not isinstance(content, dict) or not isinstance(content.get('blocks'), list):
        return ''
    strip = re.compile(r'<[^>]*>')

    def plain(s):
        from html import unescape
        return unescape(strip.sub('', (s or '').replace('<br>', '\n'))) if isinstance(s, str) else ''

    def walk(items, depth=0):
        lines = []
        for i in items if isinstance(items, list) else []:
            if isinstance(i, str):
                lines.append('  ' * depth + '- ' + plain(i))
            elif isinstance(i, dict):
                lines.append('  ' * depth + '- ' + plain(i.get('content', i.get('text'))))
                lines.extend(walk(i.get('items'), depth + 1))
        return lines

    paras = []
    for b in content['blocks']:
        if not isinstance(b, dict):
            continue
        d = b.get('data') if isinstance(b.get('data'), dict) else {}
        if b.get('type') in ('paragraph', 'header', 'quote'):
            paras.append(plain(d.get('text')))
        elif b.get('type') in ('list', 'checklist'):
            paras.append('\n'.join(walk(d.get('items'))))
        elif b.get('type') == 'code':
            paras.append(d.get('code', ''))
    return '\n\n'.join(p for p in paras if p)

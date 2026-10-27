from django import template

from ..notes_render import render_blocks

register = template.Library()


@register.filter
def render_note(content, top_level=3):
    """{{ note.content|render_note }} — Editor.js JSON to sanitized HTML.

    Optional arg sets the heading level used for Editor.js level-2 headers
    (level-3 headers render one level deeper), e.g. ``|render_note:4``.
    """
    try:
        top_level = int(top_level)
    except (TypeError, ValueError):
        top_level = 3
    return render_blocks(content, top_level=top_level)

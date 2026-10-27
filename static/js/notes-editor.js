/* Notes editor: Editor.js with a plain <textarea> fallback.
   Loaded (deferred) after the Editor.js CDN scripts; if any of them failed,
   the textarea stays visible and is submitted instead. */
(function () {
  'use strict';

  var form = document.getElementById('note-form');
  if (!form) return;
  var holder = document.getElementById('note-editor');
  var help = document.getElementById('editor-help');
  var fallback = document.getElementById('note-fallback');
  var textarea = document.getElementById('note-text');
  var hidden = document.getElementById('note-content');
  var status = document.getElementById('note-status');
  var saveBtn = document.getElementById('note-save');

  var editor = null;
  var dirty = false;
  var submitting = false;

  function say(msg) { if (status) status.textContent = msg; }

  function initialData() {
    try {
      var el = document.getElementById('note-initial');
      var data = el ? JSON.parse(el.textContent) : null;
      if (data && Array.isArray(data.blocks)) return data;
    } catch (e) { /* fall through */ }
    return { blocks: [] };
  }

  function haveTools() {
    return typeof window.EditorJS === 'function' && window.Header && window.EditorjsList &&
      window.Checklist && window.Quote && window.Delimiter && window.InlineCode && window.Marker;
  }

  function showFallback(reason) {
    holder.hidden = true;
    if (help) help.hidden = true;
    fallback.hidden = false;
    textarea.disabled = false;
    if (reason) say(reason);
  }

  function initEditor() {
    if (!haveTools()) {
      showFallback('Rich editor could not load. Plain text mode.');
      return;
    }
    try {
      editor = new window.EditorJS({
        holder: holder,
        data: initialData(),
        placeholder: "Write something, or type '/' for blocks",
        minHeight: 120,
        tools: {
          header: {
            class: window.Header,
            inlineToolbar: true,
            config: { levels: [2, 3], defaultLevel: 2, placeholder: 'Heading' }
          },
          list: {
            class: window.EditorjsList,
            inlineToolbar: true,
            config: { defaultStyle: 'unordered', maxLevel: 4 }
          },
          checklist: { class: window.Checklist, inlineToolbar: true },
          quote: {
            class: window.Quote,
            inlineToolbar: true,
            config: { quotePlaceholder: 'Quote', captionPlaceholder: 'Source (optional)' }
          },
          delimiter: window.Delimiter,
          inlineCode: { class: window.InlineCode, shortcut: 'CMD+SHIFT+M' },
          marker: { class: window.Marker, shortcut: 'CMD+SHIFT+H' }
        },
        onChange: function () { dirty = true; }
      });
    } catch (e) {
      showFallback('Rich editor could not start. Plain text mode.');
      return;
    }

    // Swap the textarea out only once the editor is actually usable.
    editor.isReady.then(function () {
      holder.hidden = false;
      if (help) help.hidden = false;
      fallback.hidden = true;
      textarea.disabled = true; // not submitted; JSON is
    }).catch(function () {
      editor = null;
      showFallback('Rich editor could not start. Plain text mode.');
    });
  }

  function submit(stay) {
    if (submitting) return;
    var cont = form.querySelector('input[name="continue"]');
    if (stay && !cont) {
      cont = document.createElement('input');
      cont.type = 'hidden';
      cont.name = 'continue';
      cont.value = '1';
      form.appendChild(cont);
    } else if (!stay && cont) {
      cont.remove();
    }

    if (!editor || holder.hidden) {
      hidden.value = '';
      submitting = true;
      dirty = false;
      form.submit();
      return;
    }
    submitting = true;
    if (saveBtn) saveBtn.disabled = true;
    say('Saving…');
    editor.save().then(function (data) {
      hidden.value = JSON.stringify(data);
      dirty = false;
      form.submit(); // native submit: does not re-fire the submit event
    }).catch(function () {
      submitting = false;
      if (saveBtn) saveBtn.disabled = false;
      say('Could not read the editor content. Please try again.');
    });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    submit(false);
  });

  // Ctrl/Cmd+S saves and stays on the editor.
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 's' || e.key === 'S')) {
      e.preventDefault();
      submit(true);
    }
  });

  ['input', 'change'].forEach(function (type) {
    form.addEventListener(type, function (e) {
      if (e.target && e.target.closest && !e.target.closest('#note-editor')) dirty = true;
    });
  });

  window.addEventListener('beforeunload', function (e) {
    if (dirty && !submitting) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  initEditor();
})();

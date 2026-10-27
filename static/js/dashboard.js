/* Dashboard enhancements. Every feature also works without this script. */
(function () {
  'use strict';

  /* ---------------------------------------------------- confirm prompts */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    var msg = form.getAttribute && form.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  /* ---------------------------------------------- slug suggestion (spaces) */
  var slugForm = document.querySelector('form[data-slugify]');
  if (slugForm) {
    var name = slugForm.querySelector('[name="name"]');
    var slug = slugForm.querySelector('[name="slug"]');
    var touched = slugForm.hasAttribute('data-slug-locked') || (slug && slug.value !== '');
    var slugify = function (s) {
      return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
        .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
    };
    if (name && slug) {
      slug.addEventListener('input', function () { touched = slug.value !== ''; });
      name.addEventListener('input', function () { if (!touched) slug.value = slugify(name.value); });
    }
  }

  /* ----------------------------------- copy form: confirm only for replace */
  document.querySelectorAll('.copy-form').forEach(function (form) {
    var confirmBox = form.querySelector('[name="confirm_replace"]');
    var radios = form.querySelectorAll('input[name="mode"][type="radio"]');
    if (!confirmBox || !radios.length) return;
    var wrap = confirmBox.closest('.field');
    var sync = function () {
      var checked = form.querySelector('input[name="mode"]:checked');
      wrap.hidden = !!checked && checked.value === 'merge';
    };
    radios.forEach(function (r) { r.addEventListener('change', sync); });
    sync();
  });

  /* ------------------------------------------------- session side dialog */
  var dialog = document.getElementById('session-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  var body = dialog.querySelector('[data-dialog-body]');
  var title = dialog.querySelector('#session-dialog-title');
  var trigger = null;

  function focusFirst() {
    var el = body.querySelector('[aria-invalid="true"], input:not([type=hidden]), select, textarea, button');
    if (el) el.focus();
  }

  function open(link) {
    var url = new URL(link.href, window.location.href);
    url.searchParams.set('partial', '1');
    trigger = link;
    link.setAttribute('aria-busy', 'true');
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        body.innerHTML = html;
        var root = body.querySelector('[data-title]');
        if (root) title.textContent = root.getAttribute('data-title');
        dialog.showModal();
        focusFirst();
      })
      .catch(function () { window.location.href = link.href; })
      .finally(function () { link.removeAttribute('aria-busy'); });
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest('a[data-dialog]');
    if (link) { e.preventDefault(); open(link); return; }
    if (e.target.closest('[data-dialog-close]') && dialog.contains(e.target)) {
      e.preventDefault();
      dialog.close();
    }
  });

  // Clicking the backdrop (outside the panel box) closes the dialog.
  dialog.addEventListener('click', function (e) {
    if (e.target !== dialog) return;
    var r = dialog.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
  });

  // Esc fires "cancel" then "close" natively; return focus to the trigger.
  dialog.addEventListener('close', function () {
    body.innerHTML = '';
    if (trigger && document.contains(trigger)) trigger.focus();
    trigger = null;
  });
})();

// Public timetable: mobile day tabs + group filter. Progressive enhancement only.
(function () {
  var root = document.querySelector('.tt');
  if (!root) return;

  // ---- day tabs (ARIA tabs pattern, automatic activation)
  var days = root.querySelector('[data-days]');
  if (days) {
    var list = days.querySelector('[role=tablist]');
    var tabs = [].slice.call(list.querySelectorAll('[role=tab]'));
    var panels = tabs.map(function (t) { return document.getElementById(t.getAttribute('aria-controls')); });
    var select = function (i, focus) {
      tabs.forEach(function (t, j) {
        var on = i === j;
        t.setAttribute('aria-selected', on);
        t.tabIndex = on ? 0 : -1;
        panels[j].hidden = !on;
      });
      if (focus) tabs[i].focus();
    };
    panels.forEach(function (p, j) {
      p.setAttribute('role', 'tabpanel');
      p.setAttribute('aria-labelledby', tabs[j].id);
      p.tabIndex = 0;
    });
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { select(i); });
      t.addEventListener('keydown', function (e) {
        var n = tabs.length, k = e.key, to = null;
        if (k === 'ArrowRight') to = (i + 1) % n;
        else if (k === 'ArrowLeft') to = (i - 1 + n) % n;
        else if (k === 'Home') to = 0;
        else if (k === 'End') to = n - 1;
        if (to !== null) { e.preventDefault(); select(to, true); }
      });
    });
    list.hidden = false;
    days.classList.add('has-tabs');
    select(parseInt(days.dataset.defaultDay, 10) || 0);
  }

  // ---- group filter, persisted per space
  var filter = root.querySelector('[data-filter]');
  if (!filter) return;
  var key = 'tt-group:' + root.dataset.space;
  var buttons = [].slice.call(filter.querySelectorAll('button[data-group]'));
  var items = [].slice.call(root.querySelectorAll('.sess[data-groups], .tt-removed li[data-groups]'));

  var apply = function (g) {
    if (!buttons.some(function (b) { return b.dataset.group === g; })) g = '';
    buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.group === g); });
    items.forEach(function (el) {
      var gs = el.dataset.groups.split(' ').filter(Boolean);
      el.classList.toggle('is-hidden', !!g && gs.length > 0 && gs.indexOf(g) < 0);
    });
    if (days) {
      [].forEach.call(days.querySelectorAll('.tt-day-panel'), function (p) {
        p.querySelector('.tt-day-empty').hidden = !!p.querySelector('.sess:not(.is-hidden)');
      });
    }
    try { localStorage.setItem(key, g); } catch (e) {}
  };

  buttons.forEach(function (b) {
    b.addEventListener('click', function () { apply(b.dataset.group); });
  });
  var saved = '';
  try { saved = localStorage.getItem(key) || ''; } catch (e) {}
  filter.hidden = false;
  apply(saved);
})();

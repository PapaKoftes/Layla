/**
 * components/command-palette.js — ⌘K command palette (GUI rebuild G2).
 *
 * A calm, Linear/Raycast-style overlay for the primary gestures: switch aspect,
 * jump to a screen, run a chat action. Vanilla ES module, zero deps, styled
 * entirely from the G1 token layer (var(--surface-2)/--accent/--border,
 * JetBrains Mono) so it re-themes with the active aspect for free.
 *
 * main.js owns the command list (it holds the module refs) and calls
 * initCommandPalette(commands). openCommandPalette() is bound to ⌘K in
 * bootstrap.js. Each command is { id, label, group, hint?, icon?, keywords?, run }.
 */

let _commands = [];
let _root = null;
let _input = null;
let _list = null;
let _empty = null;
let _items = [];   // [{ cmd, el }] currently rendered
let _sel = 0;
let _open = false;

function _norm(s) {
  return (s || '').toString().toLowerCase().trim();
}

function _build() {
  if (_root) return;
  _root = document.createElement('div');
  _root.id = 'cmd-palette';
  _root.className = 'cmdp-backdrop';
  _root.setAttribute('role', 'dialog');
  _root.setAttribute('aria-modal', 'true');
  _root.setAttribute('aria-label', 'Command palette');
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel" role="document">' +
      '<div class="cmdp-search-row">' +
        '<span class="cmdp-search-icon" aria-hidden="true">⌘</span>' +
        '<input class="cmdp-input" type="text" placeholder="Type a command or search…" ' +
          'autocomplete="off" autocapitalize="off" spellcheck="false" ' +
          'aria-label="Search commands" role="combobox" aria-expanded="true" aria-controls="cmdp-list" />' +
        '<kbd class="cmdp-esc">esc</kbd>' +
      '</div>' +
      '<div class="cmdp-list" id="cmdp-list" role="listbox"></div>' +
      '<div class="cmdp-empty" hidden>no matching commands</div>' +
    '</div>';
  document.body.appendChild(_root);
  _input = _root.querySelector('.cmdp-input');
  _list = _root.querySelector('.cmdp-list');
  _empty = _root.querySelector('.cmdp-empty');

  // Click on the dim backdrop (but not the panel) closes.
  _root.addEventListener('mousedown', function (e) {
    if (e.target === _root) closeCommandPalette();
  });
  _input.addEventListener('input', function () { _render(_input.value); });
  _input.addEventListener('keydown', _onKey);
}

function _matches(cmd, terms) {
  if (!terms.length) return true;
  const hay = _norm(cmd.label) + ' ' + _norm(cmd.group) + ' ' +
    _norm(cmd.hint) + ' ' + _norm((cmd.keywords || []).join(' '));
  return terms.every(function (t) { return hay.indexOf(t) !== -1; });
}

function _render(query) {
  const terms = _norm(query).split(/\s+/).filter(Boolean);
  const matched = _commands.filter(function (c) { return _matches(c, terms); });
  _list.innerHTML = '';
  _items = [];
  let lastGroup = null;
  matched.forEach(function (cmd) {
    if (cmd.group && cmd.group !== lastGroup) {
      const h = document.createElement('div');
      h.className = 'cmdp-group';
      h.textContent = cmd.group;
      _list.appendChild(h);
      lastGroup = cmd.group;
    }
    const el = document.createElement('div');
    el.className = 'cmdp-item';
    el.setAttribute('role', 'option');
    if (cmd.icon) {
      const ic = document.createElement('span');
      ic.className = 'cmdp-item-icon';
      ic.setAttribute('aria-hidden', 'true');
      ic.textContent = cmd.icon;
      el.appendChild(ic);
    }
    const lab = document.createElement('span');
    lab.className = 'cmdp-item-label';
    lab.textContent = cmd.label;
    el.appendChild(lab);
    if (cmd.hint) {
      const hint = document.createElement('span');
      hint.className = 'cmdp-item-hint';
      hint.textContent = cmd.hint;
      el.appendChild(hint);
    }
    const idx = _items.length;
    el.addEventListener('mousemove', function () { _selectIndex(idx); });
    el.addEventListener('click', function () { _run(idx); });
    _list.appendChild(el);
    _items.push({ cmd: cmd, el: el });
  });
  _empty.hidden = _items.length > 0;
  _sel = 0;
  _paint();
}

function _paint() {
  for (let i = 0; i < _items.length; i++) {
    const on = i === _sel;
    _items[i].el.classList.toggle('is-sel', on);
    _items[i].el.setAttribute('aria-selected', on ? 'true' : 'false');
    if (on) _items[i].el.scrollIntoView({ block: 'nearest' });
  }
}

function _selectIndex(i) {
  if (i >= 0 && i < _items.length) { _sel = i; _paint(); }
}

function _run(i) {
  const it = _items[i];
  if (!it) return;
  closeCommandPalette();
  try {
    it.cmd.run();
  } catch (e) {
    console.error('[cmdp] command failed:', it.cmd.id, e);
  }
}

function _onKey(e) {
  const n = _items.length;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _sel = n ? (_sel + 1) % n : 0;
    _paint();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    _sel = n ? (_sel - 1 + n) % n : 0;
    _paint();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    _run(_sel);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeCommandPalette();
  }
}

/** Register the command list (array of { id, label, group, hint?, icon?, keywords?, run }). */
export function initCommandPalette(commands) {
  _commands = Array.isArray(commands) ? commands.slice() : [];
  _build();
}

/** Replace the command list at runtime (e.g. after aspects change). */
export function setCommands(commands) {
  _commands = Array.isArray(commands) ? commands.slice() : [];
}

export function openCommandPalette() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _input.value = '';
  _render('');
  requestAnimationFrame(function () { try { _input.focus(); } catch (_) {} });
}

export function closeCommandPalette() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

export function isCommandPaletteOpen() {
  return _open;
}

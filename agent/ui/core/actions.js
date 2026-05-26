/**
 * core/actions.js — Centralized event delegation router.
 *
 * Replaces inline onclick/onchange/oninput/onkeydown handlers with
 * data-action attributes routed through a single document-level listener.
 *
 * Usage in HTML:
 *   <button data-action="openSettings">Settings</button>
 *   <button data-action="exportChat toggleHeaderOverflow">Export</button>
 *   <button data-action="setAspect" data-arg="morrigan">Morrigan</button>
 *   <button data-action="showResearchTab" data-arg="summary">Summary</button>
 *   <select data-on-change="onProjectSelectChange">...</select>
 *   <input data-on-input="onMemorySearch" data-pass-value="true">
 *   <input data-on-keydown-enter="addStudyPlan">
 *
 * The router resolves action names against a registered action map.
 * Actions are registered by modules during init.
 */

const _actions = Object.create(null);

/**
 * Register one or more actions.
 * @param {Object<string, Function>} map  { actionName: handlerFn, ... }
 */
export function registerActions(map) {
  for (const key in map) {
    if (Object.prototype.hasOwnProperty.call(map, key)) {
      _actions[key] = map[key];
    }
  }
}

/**
 * Execute a single action by name, with optional argument.
 */
function _exec(name, arg, event) {
  const fn = _actions[name];
  if (typeof fn === 'function') {
    if (arg !== undefined && arg !== null) {
      fn(arg, event);
    } else {
      fn(event);
    }
    return true;
  }
  // Fallback: check window.* for compat
  if (typeof window[name] === 'function') {
    if (arg !== undefined && arg !== null) {
      window[name](arg, event);
    } else {
      window[name](event);
    }
    return true;
  }
  console.debug('[actions] unknown action:', name);
  return false;
}

/**
 * Parse and execute action string (may be space-separated for compound actions).
 */
function _execAction(actionStr, arg, event) {
  if (!actionStr) return;
  const names = actionStr.trim().split(/\s+/);
  for (let i = 0; i < names.length; i++) {
    _exec(names[i], i === 0 ? arg : undefined, event);
  }
}

/**
 * Initialize event delegation on the document.
 */
export function initActions() {
  // ── Click delegation ──
  document.addEventListener('click', function (e) {
    // Walk up from target to find closest [data-action]
    var el = e.target;
    while (el && el !== document) {
      var action = el.getAttribute('data-action');
      if (action) {
        var arg = el.getAttribute('data-arg');
        // Parse arg: try boolean/number, else string
        if (arg !== null) {
          if (arg === 'true') arg = true;
          else if (arg === 'false') arg = false;
          else if (arg !== '' && !isNaN(Number(arg))) arg = Number(arg);
        } else {
          arg = undefined;
        }
        _execAction(action, arg, e);
        // Don't preventDefault — let links work, but do stop bubbling for action buttons
        if (el.tagName === 'BUTTON' || el.hasAttribute('data-action-stop')) {
          e.stopPropagation();
        }
        return;
      }
      el = el.parentElement;
    }
  });

  // ── Change delegation ──
  document.addEventListener('change', function (e) {
    var el = e.target;
    var action = el.getAttribute('data-on-change');
    if (!action) return;
    var passValue = el.hasAttribute('data-pass-value');
    var arg = passValue ? el.value : undefined;
    // For checkboxes, pass checked state
    if (el.type === 'checkbox') arg = el.checked;
    _execAction(action, arg, e);
  });

  // ── Input delegation ──
  document.addEventListener('input', function (e) {
    var el = e.target;
    var action = el.getAttribute('data-on-input');
    if (!action) return;
    _execAction(action, el.value, e);
  });

  // ── Keydown delegation ──
  document.addEventListener('keydown', function (e) {
    var el = e.target;
    // data-on-keydown-enter="actionName" — fires on Enter key
    var enterAction = el.getAttribute('data-on-keydown-enter');
    if (enterAction && e.key === 'Enter') {
      _execAction(enterAction, undefined, e);
      return;
    }
    // data-on-keydown="actionName" — fires on any key, passes event
    var action = el.getAttribute('data-on-keydown');
    if (action) {
      _execAction(action, undefined, e);
    }
  });

  // ── Drop delegation ──
  document.addEventListener('drop', function (e) {
    var el = e.target;
    while (el && el !== document) {
      var action = el.getAttribute('data-on-drop');
      if (action) {
        e.preventDefault();
        _execAction(action, e, e);
        return;
      }
      el = el.parentElement;
    }
  });

  // Prevent default dragover for drop targets
  document.addEventListener('dragover', function (e) {
    var el = e.target;
    while (el && el !== document) {
      if (el.hasAttribute('data-on-drop')) {
        e.preventDefault();
        return;
      }
      el = el.parentElement;
    }
  });
}

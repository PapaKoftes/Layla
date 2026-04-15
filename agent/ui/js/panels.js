/**
 * Right-panel / Status tab: execution trace + persisted tasks.
 */
(function () {
  'use strict';

  function _cid() {
    try {
      return (typeof currentConversationId !== 'undefined' && currentConversationId) ? String(currentConversationId) : '';
    } catch (_) { return ''; }
  }

  window.laylaRefreshExecutionPanels = function () {
    var traceEl = document.getElementById('exec-trace-json');
    var tasksEl = document.getElementById('tasks-list-json');
    var q = _cid() ? ('?conversation_id=' + encodeURIComponent(_cid())) : '';
    if (traceEl) traceEl.textContent = 'Loading…';
    if (tasksEl) tasksEl.textContent = 'Loading…';
    fetch('/debug/state' + q)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (traceEl) {
          try { traceEl.textContent = JSON.stringify(d, null, 2); } catch (_) { traceEl.textContent = String(d); }
        }
      })
      .catch(function (e) {
        if (traceEl) traceEl.textContent = 'Error: ' + (e && e.message ? e.message : e);
      });
    fetch('/debug/tasks' + q + (q ? '&' : '?') + 'limit=30')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (tasksEl) {
          try { tasksEl.textContent = JSON.stringify(d, null, 2); } catch (_) { tasksEl.textContent = String(d); }
        }
      })
      .catch(function (e) {
        if (tasksEl) tasksEl.textContent = 'Error: ' + (e && e.message ? e.message : e);
      });
  };

  try {
    var _orig = window.__laylaRefreshAfterShowMainPanel;
    window.__laylaRefreshAfterShowMainPanel = function (main) {
      try { if (typeof _orig === 'function') _orig(main); } catch (_) {}
      if (main === 'status') {
        try { window.laylaRefreshExecutionPanels(); } catch (_) {}
      }
    };
  } catch (_) {}
})();

/**
 * components/panels.js — Right-panel status tab: execution trace + tasks.
 *
 * Converted from js/panels.js (IIFE → ES module).
 */

import { bus } from '../core/bus.js';
import { appState } from '../core/state.js';
import { api } from '../services/api.js';

function _cid() {
  return appState.get('chat.conversationId') || '';
}

export function refreshExecutionPanels() {
  const traceEl = document.getElementById('exec-trace-json');
  const tasksEl = document.getElementById('tasks-list-json');
  const q = _cid() ? ('?conversation_id=' + encodeURIComponent(_cid())) : '';

  if (traceEl) traceEl.textContent = 'Loading…';
  if (tasksEl) tasksEl.textContent = 'Loading…';

  api.get('/debug/state' + q, { timeout: 8000 })
    .then((d) => {
      if (traceEl) {
        try { traceEl.textContent = JSON.stringify(d, null, 2); }
        catch (_) { traceEl.textContent = String(d); }
      }
    })
    .catch((e) => {
      if (traceEl) traceEl.textContent = 'Error: ' + (e && e.message ? e.message : e);
    });

  api.get('/debug/tasks' + q + (q ? '&' : '?') + 'limit=30', { timeout: 8000 })
    .then((d) => {
      if (tasksEl) {
        try { tasksEl.textContent = JSON.stringify(d, null, 2); }
        catch (_) { tasksEl.textContent = String(d); }
      }
    })
    .catch((e) => {
      if (tasksEl) tasksEl.textContent = 'Error: ' + (e && e.message ? e.message : e);
    });
}

// Auto-refresh when status panel is shown
bus.on('overlay:opened', ({ id }) => {
  // The right panel isn't an "overlay" in the old sense; hook via the main-panel event
});

// Hook into panel tab switching
bus.on('state:changed', ({ path, value }) => {
  // Future: react to panel tab changes through state
});

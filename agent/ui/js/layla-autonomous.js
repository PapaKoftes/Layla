/**
 * Layla UI — Autonomous execution monitor (Phase 2.2)
 * Real-time progress polling, step counter, pause/stop, outcome display.
 * Depends on: showToast, operatorTraceLine (layla-app.js)
 */

// ─── State ────────────────────────────────────────────────────────────────────
let _autoTaskId = null;
let _autoGoal = '';
let _autoPollTimer = null;
let _autoStartTs = 0;
let _autoLastEventCount = 0;
let _autoStopped = false;

// ─── Start monitoring ─────────────────────────────────────────────────────────
function laylaAutoMonitorStart(taskId, goal) {
  _autoTaskId = taskId;
  _autoGoal = goal || '';
  _autoStartTs = Date.now();
  _autoLastEventCount = 0;
  _autoStopped = false;

  const panel = document.getElementById('auto-monitor-panel');
  if (panel) panel.style.display = '';
  _autoSetStatus('running', 'Starting…');
  _autoSetProgress(0, 0);

  clearInterval(_autoPollTimer);
  // Wrap async poll in a sync wrapper so setInterval can call it without
  // producing unhandled promise rejections on network errors.
  _autoPollTimer = setInterval(() => { _autoPoll().catch(() => {}); }, 1500);
}

async function _autoPoll() {
  if (!_autoTaskId || _autoStopped) { clearInterval(_autoPollTimer); return; }
  try {
    const res = await fetch(`/agent/tasks/${encodeURIComponent(_autoTaskId)}`);
    if (!res.ok) return;
    const data = await res.json();
    _autoHandleProgress(data);
  } catch (_) {}
}

function _autoHandleProgress(data) {
  const events = data.events || [];
  const status = data.status || 'running';
  // Guard against backend restart shrinking the events array below our cursor.
  if (events.length < _autoLastEventCount) _autoLastEventCount = 0;
  const newEvents = events.slice(_autoLastEventCount);
  _autoLastEventCount = events.length;

  // Count steps from tool events
  const toolEvents = events.filter(e => e.kind === 'autonomous_tool' || e.kind === 'tool_step');
  _autoSetProgress(toolEvents.length, data.max_steps || 0);

  // Log new events to trace dock
  newEvents.forEach(ev => {
    if (ev.kind === 'autonomous_tool') {
      const line = `▸ ${ev.tool || '?'}${ev.args_preview ? ' — ' + ev.args_preview.slice(0, 80) : ''}`;
      try { operatorTraceLine('auto', line); } catch (_) {}
    }
  });

  // Update step label
  const elapsed = Math.round((Date.now() - _autoStartTs) / 1000);
  const el = document.getElementById('auto-step-label');
  if (el) el.textContent = `Step ${toolEvents.length}${data.max_steps ? ' / ' + data.max_steps : ''} · ${elapsed}s`;

  if (status === 'done' || status === 'error' || status === 'stopped') {
    clearInterval(_autoPollTimer);
    _autoStopped = true;
    _autoSetStatus(status, status === 'done' ? 'Complete' : 'Stopped');
    if (data.result) _autoShowOutcome(data.result);
  } else {
    _autoSetStatus('running', 'Running…');
  }
}

function _autoSetProgress(current, total) {
  const bar = document.getElementById('auto-progress-fill');
  const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  if (bar) bar.style.width = (total > 0 ? pct : 30) + '%';
  const label = document.getElementById('auto-step-label');
  if (label && total > 0) label.textContent = `Step ${current} / ${total}`;
}

function _autoSetStatus(status, text) {
  const el = document.getElementById('auto-status-text');
  if (!el) return;
  el.textContent = text || status;
  el.style.color = status === 'done' ? '#4caf50' : status === 'error' || status === 'stopped' ? '#e74c3c' : 'var(--asp)';
}

// ─── Controls ─────────────────────────────────────────────────────────────────
async function laylaAutoStop() {
  if (!_autoTaskId) return;
  try {
    await fetch(`/agent/tasks/${encodeURIComponent(_autoTaskId)}/cancel`, { method: 'POST' });
    showToast && showToast('Stop requested');
  } catch (err) {
    showToast && showToast('Stop failed: ' + err.message);
  }
  clearInterval(_autoPollTimer);
  _autoStopped = true;
  _autoSetStatus('stopped', 'Stopped by user');
}

function laylaAutoMonitorClose() {
  clearInterval(_autoPollTimer);
  const panel = document.getElementById('auto-monitor-panel');
  if (panel) panel.style.display = 'none';
  _autoTaskId = null;
}

// ─── Outcome display (Phase 2.4) ──────────────────────────────────────────────
function _autoShowOutcome(result) {
  const el = document.getElementById('auto-outcome-panel');
  if (!el) return;
  el.style.display = '';

  const score = result.outcome_score ?? result.score ?? null;
  const summary = result.summary || result.response || result.output || '';
  const issues = result.issues || result.warnings || [];
  const steps_done = (result.steps || []).filter(s => s.status === 'done').length;
  const steps_total = (result.steps || []).length;

  let html = '';
  if (score !== null) {
    const pct = Math.round(Number(score) * 100);
    const col = pct >= 75 ? '#4caf50' : pct >= 50 ? '#f7c94b' : '#e74c3c';
    html += `<div style="font-size:0.8rem;font-weight:bold;color:${col};margin-bottom:6px">Score: ${pct}%</div>`;
  }
  if (steps_total) {
    html += `<div style="font-size:0.68rem;color:var(--text-dim);margin-bottom:4px">${steps_done}/${steps_total} steps completed</div>`;
  }
  if (summary) {
    html += `<div style="font-size:0.7rem;color:var(--text);margin-bottom:6px;white-space:pre-wrap;word-break:break-word;max-height:120px;overflow-y:auto">${_aesc(summary.slice(0, 600))}${summary.length > 600 ? '…' : ''}</div>`;
  }
  if (issues.length) {
    html += `<div style="font-size:0.65rem;color:#f7c94b;margin-top:4px">⚠ Issues: ${issues.map(i => _aesc(String(i).slice(0, 80))).join('; ')}</div>`;
  }
  el.innerHTML = html || '<span style="color:var(--text-dim);font-size:0.7rem">Run complete.</span>';
}

function _aesc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── Hook into existing laylaRunAutonomousResearch ────────────────────────────
// Wrap the existing function after page load to inject monitoring
document.addEventListener('DOMContentLoaded', () => {
  const orig = window.laylaRunAutonomousResearch;
  if (typeof orig !== 'function') return;
  window.laylaRunAutonomousResearch = async function() {
    window._laylaCurrentAutoTaskId = null;
    const goalEl = document.getElementById('autonomous-goal');
    const goal = goalEl ? goalEl.value.trim() : '';
    // Call orig — it runs synchronously until its first await (the fetch),
    // setting window._laylaCurrentAutoTaskId before yielding control back here.
    const runPromise = orig.call(this, ...arguments);
    const taskId = window._laylaCurrentAutoTaskId || ('auto_' + Date.now());
    window._laylaAutoMonitorTaskId = taskId;
    laylaAutoMonitorStart(taskId, goal);
    try {
      await runPromise;
    } finally {
      setTimeout(() => { _autoPoll().catch(() => {}); }, 500);
    }
  };
});

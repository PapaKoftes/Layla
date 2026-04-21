/**
 * Layla UI — Plan Gantt Visualization (Phase 2.1)
 * Canvas-based Gantt chart for engine plans. Warframe aesthetic.
 * Depends on: showMainPanel, showToast (layla-app.js)
 */

// ─── State ────────────────────────────────────────────────────────────────────
let _vizPlanId = null;
let _vizData = null;

// ─── Public entry point ───────────────────────────────────────────────────────
async function laylaShowPlanViz(planId) {
  _vizPlanId = planId;

  const overlay = document.getElementById('plan-viz-overlay');
  if (overlay) overlay.style.display = 'flex';
  const canvas = document.getElementById('plan-viz-canvas');
  if (canvas) { const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height); }
  const info = document.getElementById('plan-viz-title');
  if (info) info.textContent = 'Loading…';
  const similar = document.getElementById('plan-viz-similar');
  if (similar) similar.style.display = 'none';

  try {
    const res = await fetch('/plans/' + encodeURIComponent(planId) + '/viz');
    if (!res.ok) throw new Error(res.status);
    _vizData = await res.json();
    if (!_vizData.ok) throw new Error(_vizData.error || 'load failed');
    _renderViz(_vizData);
    _renderSimilarPlans(_vizData.goal || '');
  } catch (err) {
    if (info) info.textContent = 'Error loading plan: ' + err.message;
  }
}

function laylaCloseViz() {
  const overlay = document.getElementById('plan-viz-overlay');
  if (overlay) overlay.style.display = 'none';
  _vizPlanId = null;
  _vizData = null;
}

// ─── Render Gantt ─────────────────────────────────────────────────────────────
function _renderViz(data) {
  const steps = data.steps || [];
  const info = document.getElementById('plan-viz-title');
  const canvas = document.getElementById('plan-viz-canvas');
  if (!canvas) return;

  const totalMs = data.total_estimated_ms || 1;
  const estSec = Math.round(totalMs / 1000);

  if (info) info.innerHTML =
    '<strong>' + _vesc(data.goal || '') + '</strong><br>' +
    '<span style="font-size:0.65rem;color:var(--text-dim)">' +
    steps.length + ' steps · ~' + estSec + 's est · status: <strong>' + data.status + '</strong>' +
    (data.parallel_capable ? ' · <span style="color:var(--asp)">⚡ parallelisable</span>' : '') +
    '</span>';

  // Canvas dimensions
  const W = canvas.parentElement ? Math.max(canvas.parentElement.clientWidth - 24, 300) : 560;
  const ROW_H = 36;
  const LABEL_W = 140;
  const BAR_AREA = W - LABEL_W - 12;
  const H = Math.max(steps.length * ROW_H + 40, 80);
  canvas.width = W;
  canvas.height = H;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';

  const ctx = canvas.getContext('2d');

  // Background
  ctx.fillStyle = 'rgba(10,10,26,0.95)';
  ctx.fillRect(0, 0, W, H);

  // Compute cumulative x positions based on dependency chain
  const endX = new Array(steps.length).fill(0);
  steps.forEach(function(s, i) {
    const deps = s.depends_on || [];
    const startPx = deps.length
      ? Math.max.apply(null, deps.map(function(d) { return endX[d] || 0; }))
      : 0;
    const barPx = Math.max(4, Math.round((s.estimated_duration_ms / totalMs) * BAR_AREA));
    endX[i] = startPx + barPx;
  });
  const maxEndX = Math.max.apply(null, endX.concat([1]));
  const scale = BAR_AREA / maxEndX;

  // Status → colour
  function barColor(status) {
    if (status === 'done') return '#4caf50';
    if (status === 'in_progress') return '#f7c94b';
    if (status === 'failed') return '#e74c3c';
    return '#5c6bc0';
  }

  steps.forEach(function(s, i) {
    const y = i * ROW_H + 6;
    const deps = s.depends_on || [];
    const startPx = deps.length
      ? Math.max.apply(null, deps.map(function(d) { return endX[d] || 0; })) * scale
      : 0;
    const barW = Math.max(6, Math.round((s.estimated_duration_ms / totalMs) * BAR_AREA * scale));
    const x = LABEL_W + startPx;

    // Row background (alternate)
    if (i % 2 === 0) {
      ctx.fillStyle = 'rgba(255,255,255,0.025)';
      ctx.fillRect(0, i * ROW_H, W, ROW_H);
    }

    // Step bar
    const color = barColor(s.status);
    ctx.fillStyle = color + '55';
    _roundRect(ctx, x, y, barW, ROW_H - 12, 3);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    _roundRect(ctx, x, y, barW, ROW_H - 12, 3);
    ctx.stroke();

    // Step label (left column)
    ctx.fillStyle = '#c0c0d8';
    ctx.font = '11px ui-monospace, monospace';
    ctx.textBaseline = 'middle';
    const label = (s.task || 'Step ' + (i + 1)).slice(0, 18);
    ctx.fillText(label, 4, i * ROW_H + ROW_H / 2);

    // Duration label inside bar
    if (barW > 40) {
      ctx.fillStyle = color;
      ctx.font = '10px ui-monospace, monospace';
      const dLabel = s.estimated_duration_ms >= 1000
        ? Math.round(s.estimated_duration_ms / 1000) + 's'
        : s.estimated_duration_ms + 'ms';
      ctx.fillText(dLabel, x + 4, i * ROW_H + ROW_H / 2);
    }

    // Dependency arrows
    deps.forEach(function(d) {
      if (d < 0 || d >= steps.length) return;
      const fromX = LABEL_W + endX[d] * scale;
      const fromY = d * ROW_H + ROW_H / 2;
      const toX = x;
      const toY = i * ROW_H + ROW_H / 2;
      ctx.strokeStyle = 'rgba(155,89,182,0.5)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(fromX, fromY);
      ctx.bezierCurveTo(fromX + 10, fromY, toX - 10, toY, toX, toY);
      ctx.stroke();
      // Arrowhead
      ctx.fillStyle = 'rgba(155,89,182,0.7)';
      ctx.beginPath();
      ctx.moveTo(toX, toY);
      ctx.lineTo(toX - 6, toY - 3);
      ctx.lineTo(toX - 6, toY + 3);
      ctx.closePath();
      ctx.fill();
    });
  });

  // Divider between label and bar areas
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(LABEL_W, 0);
  ctx.lineTo(LABEL_W, H);
  ctx.stroke();
}

function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

// ─── Similar plans (Phase 2.3) ────────────────────────────────────────────────
async function _renderSimilarPlans(goal) {
  const el = document.getElementById('plan-viz-similar');
  if (!el || !goal.trim()) return;
  try {
    const res = await fetch('/plans/similar?goal=' + encodeURIComponent(goal) + '&limit=3');
    const data = await res.json();
    const items = (data.similar || []).filter(function(p) { return p.plan_id !== _vizPlanId; });
    if (!items.length) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.innerHTML = '<div style="font-size:0.65rem;color:var(--asp);margin-bottom:4px">Similar past plans</div>' +
      items.map(function(p) {
        return '<div style="font-size:0.65rem;padding:3px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">' +
          '<span style="color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + _vesc(p.goal) + '</span>' +
          '<span style="color:var(--text-dim);margin-left:8px;white-space:nowrap">' + p.step_count + ' steps · ' + p.status + ' · ' + Math.round(p.similarity * 100) + '% match</span>' +
          '</div>';
      }).join('');
  } catch (_) {
    el.style.display = 'none';
  }
}

function _vesc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

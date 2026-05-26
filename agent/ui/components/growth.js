/**
 * components/growth.js — Growth dashboard panel logic.
 *
 * Converted from js/layla-growth.js (IIFE -> ES module).
 * Fetches /api/growth/stats AND /operator/profile to populate
 * XP progress, rank badge, velocity sparkline, verification stats.
 */

import { escapeHtml } from '../services/utils.js';

// ── State ───────────────────────────────────────────────────────────────────
let _refreshing = false;

// XP thresholds per rank (rank N requires this much XP from rank N-1)
const _XP_THRESHOLDS = [
  500, 1000, 2000, 3000, 5000, 8000, 12000, 18000, 26000, 36000, 50000, 70000, 100000
];

// ── Helpers ─────────────────────────────────────────────────────────────────
function _esc(s) {
  return escapeHtml(String(s || ''));
}

function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(val != null ? val : '—');
}

function _fmtNum(n) {
  if (n == null) return '—';
  n = parseInt(n, 10);
  if (isNaN(n)) return '—';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

// ── Fetch + populate ────────────────────────────────────────────────────────
export function refreshGrowthDashboard() {
  if (_refreshing) return;
  _refreshing = true;

  Promise.all([
    fetch('/api/growth/stats').then(r => r.json()),
    fetch('/operator/profile').then(r => r.json()),
  ]).then(([stats, profile]) => {
    _refreshing = false;
    if (stats && stats.ok) _populateStats(stats);
    if (profile) _populateMaturity(profile);
  }).catch(e => {
    _refreshing = false;
    console.warn('[Layla Growth] fetch failed:', e);
  });
}

// ── Maturity (XP bar, rank badge, unlocks) ──────────────────────────────────
function _populateMaturity(p) {
  const maturity = p.maturity || {};
  const rank = maturity.rank || 0;
  const xp = maturity.xp || 0;
  const phase = maturity.phase || 'awakening';
  const unlocks = maturity.unlocks || [];

  // XP Progress bar
  const xpNeeded = rank < _XP_THRESHOLDS.length ? _XP_THRESHOLDS[rank] : 100000;
  const xpPct = Math.min(100, Math.round((xp / xpNeeded) * 100));
  const barEl = document.getElementById('growth-xp-bar-fill');
  if (barEl) {
    barEl.style.width = xpPct + '%';
    barEl.style.background = _phaseGradient(phase);
  }
  _setText('growth-xp-current', xp.toLocaleString());
  _setText('growth-xp-needed', xpNeeded.toLocaleString());
  _setText('growth-xp-pct', xpPct + '%');

  // Rank badge
  const badgeEl = document.getElementById('growth-rank-badge');
  if (badgeEl) {
    badgeEl.textContent = 'Rank ' + rank;
    badgeEl.className = 'growth-rank-badge phase-' + phase;
  }
  _setText('growth-phase-name', _phaseDisplayName(phase));

  // Unlocks list
  const ulEl = document.getElementById('growth-unlocks-list');
  if (ulEl) {
    if (unlocks.length === 0) {
      ulEl.innerHTML = '<div class="growth-unlock-empty">Earn XP to unlock abilities</div>';
    } else {
      let html = '';
      for (let i = 0; i < unlocks.length; i++) {
        const u = unlocks[i];
        html += '<div class="growth-unlock-item">';
        html += '<span class="growth-unlock-icon">✦</span>';
        html += '<span class="growth-unlock-name">' + _esc(u.name || '') + '</span>';
        html += '<span class="growth-unlock-rank">Rank ' + (u.rank_required || 0) + '</span>';
        html += '</div>';
      }
      // Show next unlock if not all earned
      if (unlocks.length < 6) {
        const nextRanks = [1, 3, 5, 7, 10, 12];
        const nextNames = ['Proactive suggestions', 'Research autonomy', 'Multi-step planning',
                           'Cross-aspect synthesis', 'Full autonomy mode', 'Teacher mode'];
        for (let j = 0; j < nextRanks.length; j++) {
          if (rank < nextRanks[j]) {
            html += '<div class="growth-unlock-item growth-unlock-locked">';
            html += '<span class="growth-unlock-icon">🔒</span>';
            html += '<span class="growth-unlock-name">' + nextNames[j] + '</span>';
            html += '<span class="growth-unlock-rank">Rank ' + nextRanks[j] + '</span>';
            html += '</div>';
            break;
          }
        }
      }
      ulEl.innerHTML = html;
    }
  }
}

function _phaseDisplayName(phase) {
  const map = {
    awakening: 'Awakening',
    attunement: 'Attunement',
    resonance: 'Resonance',
    sovereignty: 'Sovereignty',
    transcendence: 'Transcendence',
  };
  return map[phase] || phase;
}

function _phaseGradient(phase) {
  const gradients = {
    awakening: 'linear-gradient(90deg, #4ecdc4, #44a08d)',
    attunement: 'linear-gradient(90deg, #f093fb, #f5576c)',
    resonance: 'linear-gradient(90deg, #4facfe, #00f2fe)',
    sovereignty: 'linear-gradient(90deg, #fa709a, #fee140)',
    transcendence: 'linear-gradient(90deg, #a18cd1, #fbc2eb)',
  };
  return gradients[phase] || gradients.awakening;
}

// ── Stats population ────────────────────────────────────────────────────────
function _populateStats(d) {
  // Top stat cards
  _setText('growth-total-facts', _fmtNum(d.total_facts));
  _setText('growth-verified-pct', _calcVerifiedPct(d));
  _setText('growth-week-count', _fmtNum(d.learnings_last_7_days));
  _setText('growth-pending-verify', _pendingCount(d));

  // Verification stats breakdown
  const v = d.verification || {};
  _setText('growth-verify-confirmed', _fmtNum(v.confirmed || 0));
  _setText('growth-verify-rejected', _fmtNum(v.rejected || 0));
  _setText('growth-verify-pending', _fmtNum(v.pending || 0));

  // Velocity sparkline (last 4 weeks)
  _renderVelocitySparkline(d.velocity_by_week || []);

  // Capabilities list
  _renderCapabilities(d.capabilities || []);

  // Learning types
  _renderTypes(d.learning_types || {});

  // Knowledge watcher status
  _renderWatcher(d.knowledge_watcher || {});
}

function _calcVerifiedPct(d) {
  const total = d.total_facts || 0;
  const high = d.high_confidence_facts || 0;
  if (total === 0) return '—';
  return Math.round((high / total) * 100) + '%';
}

function _pendingCount(d) {
  const v = d.verification || {};
  return _fmtNum(v.pending || 0);
}

// ── Velocity sparkline ──────────────────────────────────────────────────────
function _renderVelocitySparkline(weeks) {
  const el = document.getElementById('growth-velocity-sparkline');
  if (!el) return;

  if (!weeks || weeks.length === 0) {
    el.innerHTML = '<span style="color:var(--text-dim);font-size:0.6rem">No velocity data yet</span>';
    return;
  }

  const data = weeks.slice(-4);
  const max = Math.max(...data.map(w => w.count || 0));
  const safeMax = max === 0 ? 1 : max;

  let html = '<div style="display:flex;align-items:flex-end;gap:2px;height:32px">';
  for (let i = 0; i < data.length; i++) {
    const count = data[i].count || 0;
    const h = Math.max(2, Math.round((count / safeMax) * 28));
    const label = data[i].label || ('W' + (i + 1));
    html += '<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:1px">';
    html += '<div style="width:100%;height:' + h + 'px;background:var(--accent);border-radius:2px;min-width:8px" title="' + _esc(label) + ': ' + count + ' learnings"></div>';
    html += '<span style="font-size:0.45rem;color:var(--text-dim)">' + count + '</span>';
    html += '</div>';
  }
  html += '</div>';
  el.innerHTML = html;
}

// ── Capabilities ────────────────────────────────────────────────────────────
function _renderCapabilities(caps) {
  const el = document.getElementById('growth-capabilities-list');
  if (!el) return;

  if (!caps.length) {
    el.textContent = 'No capabilities tracked yet';
    return;
  }

  let html = '<div style="display:flex;flex-direction:column;gap:4px">';
  for (let i = 0; i < caps.length && i < 12; i++) {
    const c = caps[i];
    const name = _esc(c.name || 'Unknown');
    const level = (c.level || 0).toFixed(1);
    const conf = Math.round((c.confidence || 0) * 100);
    const trend = c.trend || 'stable';
    const trendIcon = trend === 'rising' ? '↑' : trend === 'falling' ? '↓' : '→';
    const trendColor = trend === 'rising' ? '#4caf50' : trend === 'falling' ? '#f44336' : 'var(--text-dim)';
    const pct = Math.min(100, Math.round((c.level || 0) * 20));

    html += '<div style="display:flex;align-items:center;gap:6px">';
    html += '<span style="flex:0 0 90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + name + '">' + name + '</span>';
    html += '<div style="flex:1;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">';
    html += '<div style="width:' + pct + '%;height:100%;background:var(--accent);border-radius:3px"></div>';
    html += '</div>';
    html += '<span style="flex:0 0 28px;text-align:right;font-size:0.6rem">' + level + '</span>';
    html += '<span style="flex:0 0 14px;color:' + trendColor + '" title="' + trend + ' (' + conf + '% conf)">' + trendIcon + '</span>';
    html += '</div>';
  }
  html += '</div>';
  if (caps.length > 12) {
    html += '<div style="font-size:0.6rem;color:var(--text-dim);margin-top:4px">+ ' + (caps.length - 12) + ' more</div>';
  }
  el.innerHTML = html;
}

function _renderTypes(types) {
  const el = document.getElementById('growth-types-list');
  if (!el) return;

  const keys = Object.keys(types);
  if (!keys.length) {
    el.textContent = 'No learnings yet';
    return;
  }

  let html = '<div style="display:flex;flex-wrap:wrap;gap:6px">';
  for (let i = 0; i < keys.length && i < 10; i++) {
    const k = keys[i];
    const count = types[k] || 0;
    html += '<span style="padding:2px 8px;border-radius:10px;font-size:0.6rem;';
    html += 'background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.12)">';
    html += _esc(k) + ' <strong>' + _fmtNum(count) + '</strong></span>';
  }
  html += '</div>';
  el.innerHTML = html;
}

function _renderWatcher(w) {
  const el = document.getElementById('growth-watcher-status');
  if (!el) return;

  if (!w || !Object.keys(w).length) {
    el.textContent = 'Knowledge watcher not active';
    return;
  }

  const running = w.running ? '● Running' : '○ Stopped';
  const runColor = w.running ? '#4caf50' : '#f44336';
  const watched = w.watched_folders || 0;
  const processed = w.files_processed || 0;
  const pending = w.files_pending || 0;

  let html = '<span style="color:' + runColor + '">' + running + '</span>';
  html += ' · ' + watched + ' folder' + (watched !== 1 ? 's' : '') + ' watched';
  html += ' · ' + _fmtNum(processed) + ' processed';
  if (pending > 0) {
    html += ' · <span style="color:#ff9800">' + pending + ' pending</span>';
  }
  el.innerHTML = html;
}

/**
 * services/health.js — Centralized health & polling service for Layla UI.
 *
 * Replaces 5+ independent setInterval polling loops in layla-app.js with a
 * single smart poller that:
 *   - Batches related API calls into one tick
 *   - Pauses when the tab is hidden (visibilitychange)
 *   - Adjusts frequency based on activity (idle → slower, active → faster)
 *   - Exposes all data through appState + bus events
 *
 * Polling groups:
 *   "fast"     (15s): /health (connection check)
 *   "normal"   (20s): /health?deep=true, /session/stats, /cluster/status
 *   "slow"     (60s): /api/growth/stats, /operator/profile
 *
 * Usage:
 *   import { healthService } from './services/health.js';
 *   healthService.start();
 *   healthService.stop();
 *   healthService.refresh();  // Force immediate poll of all groups
 */

import { bus } from '../core/bus.js';
import { appState } from '../core/state.js';
import { api } from './api.js';

// ── Polling intervals ────────────────────────────────────────────────────────
const INTERVALS = {
  fast:    15000,    // connection check
  normal:  20000,    // health deep + stats
  slow:    60000,    // growth + profile
};

// ── Timers ───────────────────────────────────────────────────────────────────
let _timers = { fast: null, normal: null, slow: null };
let _running = false;
let _paused = false;

// ── Session start time (for elapsed display) ─────────────────────────────────
let _sessionStart = Date.now();
let _sessionTimer = null;

// ── Fast group: connection check ─────────────────────────────────────────────
async function _pollFast() {
  try {
    await api.get('/health', { timeout: 5000 });
    if (navigator.onLine) {
      appState.set('health.status', 'online');
      bus.emit('health:connected');
    }
  } catch (_) {
    appState.set('health.status', 'offline');
    bus.emit('health:disconnected');
  }
}

// ── Normal group: deep health + session stats + cluster ──────────────────────
async function _pollNormal() {
  // 1. Deep health
  try {
    const d = await api.get('/health?deep=true', { timeout: 8000 });
    appState.batch({
      'health.payload':      d,
      'health.lastCheck':    Date.now(),
      'health.modelLoaded':  !!d.model_loaded,
      'health.modelName':    String(d.active_model || d.model_path || d.model || d.model_filename || '').trim(),
      'health.remoteMode':   !!d.remote_mode,
      'health.uptime':       d.uptime_seconds || 0,
      'health.status':       'online',
    });

    // Governor mode from health resource_load
    if (d.resource_load) {
      const mode = (d.resource_load.governor_mode || d.resource_load.mode || '').toLowerCase();
      if (mode) appState.set('health.governorMode', mode);
    }

    // Learnings count
    if (d.learnings != null) {
      appState.set('growth.facts', d.learnings);
    }

    bus.emit('health:deep-update', d);
  } catch (_) {
    appState.set('health.status', 'degraded');
  }

  // 2. Session stats
  try {
    const stats = await api.get('/session/stats', { timeout: 5000 });
    if (stats && !stats.error) {
      appState.batch({
        'session.tokens':    stats.total_tokens || 0,
        'session.toolCalls': stats.tool_calls || 0,
        'session.elapsed':   stats.elapsed_seconds || 0,
      });
      bus.emit('session:stats-update', stats);
    }
  } catch (_) { /* non-critical */ }

  // 3. Cluster status
  try {
    const cluster = await api.get('/cluster/status', { timeout: 5000 });
    if (cluster) {
      const peers = cluster.peers || cluster.connected_peers || 0;
      const peerCount = typeof peers === 'number' ? peers :
                        (Array.isArray(peers) ? peers.length : Object.keys(peers || {}).length);
      appState.batch({
        'cluster.enabled':  !!cluster.cluster_enabled,
        'cluster.role':     cluster.node_role || cluster.role || 'queen',
        'cluster.peers':    peerCount,
      });

      // Governor from cluster (often more reliable)
      const gm = (cluster.governor_mode || '').toLowerCase();
      if (gm && gm !== 'unknown') {
        appState.set('health.governorMode', gm);
      }

      bus.emit('cluster:status-update', cluster);
    }
  } catch (_) { /* non-critical */ }
}

// ── Slow group: growth + profile ─────────────────────────────────────────────
async function _pollSlow() {
  // 1. Growth stats
  try {
    const growth = await api.get('/api/growth/stats', { timeout: 8000 });
    if (growth && growth.ok) {
      if (growth.total_facts != null) {
        appState.set('growth.facts', growth.total_facts);
      }
      bus.emit('growth:stats-update', growth);
    }
  } catch (_) { /* non-critical */ }

  // 2. Operator profile
  try {
    const profile = await api.get('/operator/profile', { timeout: 8000 });
    if (profile) {
      const mat = profile.maturity || {};
      appState.batch({
        'growth.xp':    mat.xp || 0,
        'growth.rank':  mat.rank || 0,
        'growth.phase': mat.phase || '',
      });

      // Default aspect from profile
      if (profile.identity && profile.identity.default_aspect) {
        bus.emit('profile:default-aspect', profile.identity.default_aspect);
      }

      bus.emit('profile:update', profile);
    }
  } catch (_) { /* non-critical */ }
}

// ── Session time ticker ──────────────────────────────────────────────────────
function _tickSessionTime() {
  const elapsed = Math.floor((Date.now() - _sessionStart) / 1000);
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = elapsed % 60;
  const formatted = h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;

  bus.emit('session:time-tick', { elapsed, formatted });
}

// ── Start / Stop / Pause ─────────────────────────────────────────────────────
function _scheduleGroup(group, fn, interval) {
  if (_timers[group]) clearInterval(_timers[group]);
  _timers[group] = setInterval(() => {
    if (!_paused) fn().catch(() => {});
  }, interval);
}

function start() {
  if (_running) return;
  _running = true;
  _paused = false;

  // Initial poll (staggered to avoid burst)
  _pollFast().catch(() => {});
  setTimeout(() => _pollNormal().catch(() => {}), 500);
  setTimeout(() => _pollSlow().catch(() => {}), 1500);

  // Schedule recurring
  _scheduleGroup('fast',   _pollFast,   INTERVALS.fast);
  _scheduleGroup('normal', _pollNormal, INTERVALS.normal);
  _scheduleGroup('slow',   _pollSlow,   INTERVALS.slow);

  // Session time ticker
  _sessionTimer = setInterval(_tickSessionTime, 1000);
  _tickSessionTime();

  // Visibility change handler
  document.addEventListener('visibilitychange', _onVisibilityChange);

  // Online/offline
  window.addEventListener('online', _onOnline);
  window.addEventListener('offline', _onOffline);
}

function stop() {
  _running = false;
  for (const key in _timers) {
    if (_timers[key]) { clearInterval(_timers[key]); _timers[key] = null; }
  }
  if (_sessionTimer) { clearInterval(_sessionTimer); _sessionTimer = null; }
  document.removeEventListener('visibilitychange', _onVisibilityChange);
  window.removeEventListener('online', _onOnline);
  window.removeEventListener('offline', _onOffline);
}

function pause() {
  _paused = true;
  for (const key in _timers) {
    if (_timers[key]) { clearInterval(_timers[key]); _timers[key] = null; }
  }
  if (_sessionTimer) { clearInterval(_sessionTimer); _sessionTimer = null; }
}

function resume() {
  if (!_running) return;
  _paused = false;

  // Immediate refresh
  _pollFast().catch(() => {});
  _pollNormal().catch(() => {});
  _pollSlow().catch(() => {});

  // Restart intervals
  _scheduleGroup('fast',   _pollFast,   INTERVALS.fast);
  _scheduleGroup('normal', _pollNormal, INTERVALS.normal);
  _scheduleGroup('slow',   _pollSlow,   INTERVALS.slow);

  _sessionTimer = setInterval(_tickSessionTime, 1000);
}

/**
 * Force immediate poll of all groups.
 */
function refresh() {
  _pollFast().catch(() => {});
  _pollNormal().catch(() => {});
  _pollSlow().catch(() => {});
}

// ── Event handlers ───────────────────────────────────────────────────────────
function _onVisibilityChange() {
  if (document.hidden) {
    pause();
  } else {
    resume();
  }
}

function _onOnline() {
  appState.set('health.status', 'online');
  bus.emit('health:connected');
}

function _onOffline() {
  appState.set('health.status', 'offline');
  bus.emit('health:disconnected');
}

export const healthService = Object.freeze({
  start,
  stop,
  pause,
  resume,
  refresh,
  pollFast:   _pollFast,
  pollNormal: _pollNormal,
  pollSlow:   _pollSlow,
});

export default healthService;

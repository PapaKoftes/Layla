/**
 * components/pairing.js — Device pairing, mDNS peer discovery, and cluster UI.
 *
 * Converted from js/layla-pairing.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml, showToast, laylaConfirm)
 */

import { escapeHtml, showToast, laylaConfirm } from '../services/utils.js';

// ── Tier display helpers ────────────────────────────────────────────────────
const TIER_LABELS = { cpu: 'CPU', gpu_low: 'GPU (Low)', gpu_mid: 'GPU (Mid)', gpu_high: 'GPU (High)' };
const TIER_ICONS  = { cpu: '⚙', gpu_low: '⚡', gpu_mid: '⚡⚡', gpu_high: '⚡⚡⚡' };
const TIER_COLORS = { cpu: '#6a6a9a', gpu_low: '#8a8a00', gpu_mid: '#00aa66', gpu_high: '#00ddaa' };

// ── State ───────────────────────────────────────────────────────────────────
let _discoveryRunning = false;
let _pollTimer = null;
let _pendingPin = null;

function _esc(s) { return escapeHtml(String(s || '')); }

function _timeAgo(ts) {
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return Math.round(diff) + 's ago';
  if (diff < 3600) return Math.round(diff / 60) + 'm ago';
  if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
  return Math.round(diff / 86400) + 'd ago';
}

// ── Discovery control ───────────────────────────────────────────────────────
export async function startDiscovery() {
  try {
    const r = await fetch('/pairing/start', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      _discoveryRunning = true;
      showToast('mDNS discovery started');
      startPeerPolling();
      refreshPeeringPanel();
    } else {
      showToast(d.error || 'Failed to start discovery');
    }
  } catch (e) {
    showToast('Discovery error: ' + e.message);
  }
}

export async function stopDiscovery() {
  try {
    await fetch('/pairing/stop', { method: 'POST' });
    _discoveryRunning = false;
    stopPeerPolling();
    showToast('mDNS discovery stopped');
    refreshPeeringPanel();
  } catch (e) {
    showToast('Stop error: ' + e.message);
  }
}

// ── Peer polling ────────────────────────────────────────────────────────────
function startPeerPolling() {
  stopPeerPolling();
  _pollTimer = setInterval(() => refreshPeersList(), 10000);
  refreshPeersList();
}

function stopPeerPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

// ── Refresh peers list ──────────────────────────────────────────────────────
export async function refreshPeersList() {
  const list = document.getElementById('peers-list');
  if (!list) return;
  try {
    const r = await fetch('/pairing/peers');
    const peers = await r.json();
    if (!peers || !peers.length) {
      list.innerHTML = '<div class="peers-empty">No Layla instances found on your network.<br><span style="color:var(--text-dim);font-size:0.75rem">Make sure other devices are running Layla with mDNS enabled.</span></div>';
      return;
    }
    list.innerHTML = peers.map(p => {
      const tierLabel = TIER_LABELS[p.hardware_tier] || p.hardware_tier;
      const tierColor = TIER_COLORS[p.hardware_tier] || '#6a6a9a';
      const tierIcon = TIER_ICONS[p.hardware_tier] || '⚙';
      const models = (p.models || []).join(', ') || 'none';
      const age = p.age_seconds < 60 ? Math.round(p.age_seconds) + 's ago' : Math.round(p.age_seconds / 60) + 'm ago';
      return '<div class="peer-card" data-instance-id="' + _esc(p.instance_id) + '">' +
        '<div class="peer-card-header">' +
          '<span class="peer-name">' + _esc(p.name) + '</span>' +
          '<span class="peer-tier" style="color:' + tierColor + '">' + tierIcon + ' ' + tierLabel + '</span>' +
        '</div>' +
        '<div class="peer-card-body">' +
          '<div class="peer-detail"><span class="peer-label">IP:</span> ' + _esc(p.ip) + ':' + p.port + '</div>' +
          '<div class="peer-detail"><span class="peer-label">Models:</span> ' + _esc(models) + '</div>' +
          '<div class="peer-detail"><span class="peer-label">Version:</span> ' + _esc(p.version) + '</div>' +
          '<div class="peer-detail"><span class="peer-label">Seen:</span> ' + age + '</div>' +
        '</div>' +
        '<div class="peer-card-actions">' +
          '<button class="btn-pair" onclick="initiatePairing(\'' + _esc(p.instance_id) + '\',\'' + _esc(p.name) + '\')">Pair</button>' +
          '<button class="btn-health" onclick="checkPeerHealth(\'' + _esc(p.instance_id) + '\',this)">Ping</button>' +
        '</div>' +
      '</div>';
    }).join('');
  } catch (e) {
    list.innerHTML = '<div class="peers-empty">Error loading peers: ' + _esc(e.message) + '</div>';
  }
}

// ── Pairing flow ────────────────────────────────────────────────────────────
export async function initiatePairing(instanceId, deviceName) {
  try {
    const r = await fetch('/pairing/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instance_id: instanceId, device_name: deviceName || '' }),
    });
    const d = await r.json();
    if (!d.ok) { showToast(d.error || 'Pairing failed'); return; }
    _pendingPin = d.pin;
    showPinDialog(d.pin, d.ttl_seconds, instanceId, deviceName);
  } catch (e) {
    showToast('Pairing error: ' + e.message);
  }
}

function showPinDialog(pin, ttl, instanceId, deviceName) {
  let ov = document.getElementById('pairing-pin-overlay');
  if (!ov) {
    ov = document.createElement('div');
    ov.id = 'pairing-pin-overlay';
    ov.className = 'pairing-overlay';
    document.body.appendChild(ov);
  }
  const digits = pin.split('').map(d => '<span class="pin-digit">' + d + '</span>').join('');
  ov.innerHTML =
    '<div class="pairing-dialog">' +
      '<div class="pairing-dialog-header">Device Pairing</div>' +
      '<div class="pairing-dialog-body">' +
        '<p>Enter this PIN on <strong>' + _esc(deviceName || instanceId) + '</strong>:</p>' +
        '<div class="pin-display">' + digits + '</div>' +
        '<p class="pin-ttl">Valid for ' + ttl + ' seconds</p>' +
        '<div class="pin-countdown" id="pin-countdown"></div>' +
      '</div>' +
      '<div class="pairing-dialog-actions">' +
        '<button onclick="closePinDialog()">Cancel</button>' +
      '</div>' +
    '</div>';
  ov.classList.add('visible');

  let remaining = ttl;
  const countdown = document.getElementById('pin-countdown');
  const timer = setInterval(() => {
    remaining--;
    if (countdown) countdown.textContent = remaining + 's remaining';
    if (remaining <= 0) {
      clearInterval(timer);
      closePinDialog();
      showToast('Pairing PIN expired');
    }
  }, 1000);
  ov._timer = timer;
}

export function closePinDialog() {
  const ov = document.getElementById('pairing-pin-overlay');
  if (ov) {
    if (ov._timer) clearInterval(ov._timer);
    ov.classList.remove('visible');
    setTimeout(() => { if (ov.parentNode) ov.remove(); }, 300);
  }
  _pendingPin = null;
}

export async function confirmPairing(pin, instanceId) {
  try {
    const r = await fetch('/pairing/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin, instance_id: instanceId }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast('Paired with ' + (d.device_name || instanceId));
      closePinDialog();
      refreshPairedDevices();
      refreshPeersList();
      return true;
    }
    showToast(d.error || 'Pairing confirmation failed');
    return false;
  } catch (e) {
    showToast('Confirm error: ' + e.message);
    return false;
  }
}

// ── Paired devices list ─────────────────────────────────────────────────────
export async function refreshPairedDevices() {
  const list = document.getElementById('paired-devices-list');
  if (!list) return;
  try {
    const r = await fetch('/pairing/paired-devices');
    const devices = await r.json();
    if (!devices || !devices.length) {
      list.innerHTML = '<div class="peers-empty">No paired devices.<br><span style="color:var(--text-dim);font-size:0.75rem">Pair with discovered peers above.</span></div>';
      return;
    }
    list.innerHTML = devices.map(d => {
      const tierLabel = TIER_LABELS[d.hardware_tier] || d.hardware_tier;
      const tierColor = TIER_COLORS[d.hardware_tier] || '#6a6a9a';
      const paired = new Date(d.paired_at * 1000).toLocaleDateString();
      const seen = d.last_seen ? _timeAgo(d.last_seen) : 'unknown';
      const perms = d.permissions || {};
      const permHtml = Object.keys(perms).map(k => {
        const label = k.replace(/_/g, ' ');
        const on = !!perms[k];
        return '<label class="perm-toggle' + (on ? ' on' : '') + '">' +
          '<input type="checkbox"' + (on ? ' checked' : '') +
          ' onchange="toggleDevicePermission(\'' + _esc(d.instance_id) + '\',\'' + k + '\',this.checked)">' +
          ' ' + _esc(label) +
        '</label>';
      }).join('');
      return '<div class="paired-device-card">' +
        '<div class="paired-device-header">' +
          '<span class="paired-device-name">' + _esc(d.name) + '</span>' +
          '<span class="paired-device-tier" style="color:' + tierColor + '">' + tierLabel + '</span>' +
        '</div>' +
        '<div class="paired-device-meta">' +
          '<span>Paired: ' + paired + '</span> &middot; <span>Last seen: ' + seen + '</span>' +
        '</div>' +
        '<div class="paired-device-perms">' + permHtml + '</div>' +
        '<div class="paired-device-actions">' +
          '<button class="btn-health" onclick="checkPeerHealth(\'' + _esc(d.instance_id) + '\',this)">Ping</button>' +
          '<button class="btn-unpair" onclick="unpairDevice(\'' + _esc(d.instance_id) + '\',\'' + _esc(d.name) + '\')">Unpair</button>' +
        '</div>' +
      '</div>';
    }).join('');
  } catch (e) {
    list.innerHTML = '<div class="peers-empty">Error: ' + _esc(e.message) + '</div>';
  }
}

// ── Permission toggle ───────────────────────────────────────────────────────
export async function toggleDevicePermission(instanceId, key, value) {
  try {
    const body = {};
    body[key] = value;
    await fetch('/pairing/' + encodeURIComponent(instanceId) + '/permissions', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    showToast(key.replace(/_/g, ' ') + ': ' + (value ? 'enabled' : 'disabled'));
  } catch (_) {
    showToast('Permission update failed');
  }
}

// ── Unpair ──────────────────────────────────────────────────────────────────
export async function unpairDevice(instanceId, name) {
  if (!(await laylaConfirm('Unpair device "' + (name || instanceId) + '"?'))) return;
  try {
    const r = await fetch('/pairing/' + encodeURIComponent(instanceId), { method: 'DELETE' });
    const d = await r.json();
    if (d.ok) {
      showToast('Unpaired: ' + (name || instanceId));
      refreshPairedDevices();
    } else {
      showToast(d.error || 'Unpair failed');
    }
  } catch (e) {
    showToast('Unpair error: ' + e.message);
  }
}

// ── Peer health check ───────────────────────────────────────────────────────
export async function checkPeerHealth(instanceId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  try {
    const r = await fetch('/pairing/peer/' + encodeURIComponent(instanceId) + '/health');
    const d = await r.json();
    if (d.reachable) {
      showToast('Peer reachable (' + d.latency_ms + 'ms)');
      if (btn) { btn.textContent = d.latency_ms + 'ms'; btn.style.color = '#0f0'; }
    } else {
      showToast('Peer unreachable: ' + (d.error || 'timeout'));
      if (btn) { btn.textContent = 'Fail'; btn.style.color = '#f44'; }
    }
  } catch (_) {
    showToast('Health check error');
    if (btn) { btn.textContent = 'Error'; btn.style.color = '#f44'; }
  } finally {
    if (btn) {
      btn.disabled = false;
      setTimeout(() => { btn.textContent = 'Ping'; btn.style.color = ''; }, 3000);
    }
  }
}

// ── Full panel refresh ──────────────────────────────────────────────────────
export async function refreshPeeringPanel() {
  const toggleBtn = document.getElementById('discovery-toggle-btn');
  try {
    const r = await fetch('/pairing/status');
    const status = await r.json();
    _discoveryRunning = status.enabled;
    if (toggleBtn) {
      toggleBtn.textContent = status.enabled ? 'Stop Discovery' : 'Start Discovery';
      toggleBtn.className = status.enabled ? 'btn-discovery active' : 'btn-discovery';
    }
    const idEl = document.getElementById('pairing-instance-id');
    if (idEl) idEl.textContent = status.instance_id || '—';
    const countEl = document.getElementById('pairing-peer-count');
    if (countEl) countEl.textContent = String(status.peer_count || 0);
  } catch (_) {}
  refreshPeersList();
  refreshPairedDevices();
}

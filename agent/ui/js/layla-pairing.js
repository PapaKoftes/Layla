/**
 * layla-pairing.js — Device pairing, mDNS peer discovery, and cluster UI.
 * Depends on: layla-utils.js (escapeHtml, showToast, fetchWithTimeout)
 */
(function () {
  'use strict';

  var __esc = window.escapeHtml || function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };
  var __toast = window.showToast || function (t) { console.log('[toast]', t); };

  // ── Tier display helpers ──────────────────────────────────────────────────
  var TIER_LABELS = {
    cpu: 'CPU',
    gpu_low: 'GPU (Low)',
    gpu_mid: 'GPU (Mid)',
    gpu_high: 'GPU (High)',
  };
  var TIER_ICONS = {
    cpu: '⚙',      // gear
    gpu_low: '⚡',   // lightning
    gpu_mid: '⚡⚡',
    gpu_high: '⚡⚡⚡',
  };
  var TIER_COLORS = {
    cpu: '#6a6a9a',
    gpu_low: '#8a8a00',
    gpu_mid: '#00aa66',
    gpu_high: '#00ddaa',
  };

  // ── State ─────────────────────────────────────────────────────────────────
  var _discoveryRunning = false;
  var _pollTimer = null;
  var _pendingPin = null;

  // ── Discovery control ─────────────────────────────────────────────────────

  async function startDiscovery() {
    try {
      var r = await fetch('/pairing/start', { method: 'POST' });
      var d = await r.json();
      if (d.ok) {
        _discoveryRunning = true;
        __toast('mDNS discovery started');
        startPeerPolling();
        refreshPeeringPanel();
      } else {
        __toast(d.error || 'Failed to start discovery');
      }
    } catch (e) {
      __toast('Discovery error: ' + e.message);
    }
  }
  window.startDiscovery = startDiscovery;

  async function stopDiscovery() {
    try {
      await fetch('/pairing/stop', { method: 'POST' });
      _discoveryRunning = false;
      stopPeerPolling();
      __toast('mDNS discovery stopped');
      refreshPeeringPanel();
    } catch (e) {
      __toast('Stop error: ' + e.message);
    }
  }
  window.stopDiscovery = stopDiscovery;

  // ── Peer polling ──────────────────────────────────────────────────────────

  function startPeerPolling() {
    stopPeerPolling();
    _pollTimer = setInterval(function () {
      refreshPeersList();
    }, 10000); // every 10s
    refreshPeersList();
  }

  function stopPeerPolling() {
    if (_pollTimer) {
      clearInterval(_pollTimer);
      _pollTimer = null;
    }
  }

  // ── Refresh peers list ────────────────────────────────────────────────────

  async function refreshPeersList() {
    var list = document.getElementById('peers-list');
    if (!list) return;
    try {
      var r = await fetch('/pairing/peers');
      var peers = await r.json();
      if (!peers || !peers.length) {
        list.innerHTML = '<div class="peers-empty">No Layla instances found on your network.<br><span style="color:var(--text-dim);font-size:0.75rem">Make sure other devices are running Layla with mDNS enabled.</span></div>';
        return;
      }
      var html = peers.map(function (p) {
        var tierLabel = TIER_LABELS[p.hardware_tier] || p.hardware_tier;
        var tierColor = TIER_COLORS[p.hardware_tier] || '#6a6a9a';
        var tierIcon = TIER_ICONS[p.hardware_tier] || '⚙';
        var models = (p.models || []).join(', ') || 'none';
        var age = p.age_seconds < 60 ? Math.round(p.age_seconds) + 's ago' : Math.round(p.age_seconds / 60) + 'm ago';
        return '<div class="peer-card" data-instance-id="' + __esc(p.instance_id) + '">' +
          '<div class="peer-card-header">' +
            '<span class="peer-name">' + __esc(p.name) + '</span>' +
            '<span class="peer-tier" style="color:' + tierColor + '">' + tierIcon + ' ' + tierLabel + '</span>' +
          '</div>' +
          '<div class="peer-card-body">' +
            '<div class="peer-detail"><span class="peer-label">IP:</span> ' + __esc(p.ip) + ':' + p.port + '</div>' +
            '<div class="peer-detail"><span class="peer-label">Models:</span> ' + __esc(models) + '</div>' +
            '<div class="peer-detail"><span class="peer-label">Version:</span> ' + __esc(p.version) + '</div>' +
            '<div class="peer-detail"><span class="peer-label">Seen:</span> ' + age + '</div>' +
          '</div>' +
          '<div class="peer-card-actions">' +
            '<button class="btn-pair" onclick="initiatePairing(\'' + __esc(p.instance_id) + '\',\'' + __esc(p.name) + '\')">Pair</button>' +
            '<button class="btn-health" onclick="checkPeerHealth(\'' + __esc(p.instance_id) + '\',this)">Ping</button>' +
          '</div>' +
        '</div>';
      }).join('');
      list.innerHTML = html;
    } catch (e) {
      list.innerHTML = '<div class="peers-empty">Error loading peers: ' + __esc(e.message) + '</div>';
    }
  }
  window.refreshPeersList = refreshPeersList;

  // ── Pairing flow ──────────────────────────────────────────────────────────

  async function initiatePairing(instanceId, deviceName) {
    try {
      var r = await fetch('/pairing/pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instance_id: instanceId, device_name: deviceName || '' }),
      });
      var d = await r.json();
      if (!d.ok) {
        __toast(d.error || 'Pairing failed');
        return;
      }
      _pendingPin = d.pin;
      showPinDialog(d.pin, d.ttl_seconds, instanceId, deviceName);
    } catch (e) {
      __toast('Pairing error: ' + e.message);
    }
  }
  window.initiatePairing = initiatePairing;

  function showPinDialog(pin, ttl, instanceId, deviceName) {
    // Create or update PIN overlay
    var ov = document.getElementById('pairing-pin-overlay');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'pairing-pin-overlay';
      ov.className = 'pairing-overlay';
      document.body.appendChild(ov);
    }
    var digits = pin.split('').map(function (d) {
      return '<span class="pin-digit">' + d + '</span>';
    }).join('');

    ov.innerHTML =
      '<div class="pairing-dialog">' +
        '<div class="pairing-dialog-header">Device Pairing</div>' +
        '<div class="pairing-dialog-body">' +
          '<p>Enter this PIN on <strong>' + __esc(deviceName || instanceId) + '</strong>:</p>' +
          '<div class="pin-display">' + digits + '</div>' +
          '<p class="pin-ttl">Valid for ' + ttl + ' seconds</p>' +
          '<div class="pin-countdown" id="pin-countdown"></div>' +
        '</div>' +
        '<div class="pairing-dialog-actions">' +
          '<button onclick="closePinDialog()">Cancel</button>' +
        '</div>' +
      '</div>';
    ov.classList.add('visible');

    // Countdown
    var remaining = ttl;
    var countdown = document.getElementById('pin-countdown');
    var timer = setInterval(function () {
      remaining--;
      if (countdown) countdown.textContent = remaining + 's remaining';
      if (remaining <= 0) {
        clearInterval(timer);
        closePinDialog();
        __toast('Pairing PIN expired');
      }
    }, 1000);
    ov._timer = timer;
  }

  function closePinDialog() {
    var ov = document.getElementById('pairing-pin-overlay');
    if (ov) {
      if (ov._timer) clearInterval(ov._timer);
      ov.classList.remove('visible');
      setTimeout(function () { if (ov.parentNode) ov.remove(); }, 300);
    }
    _pendingPin = null;
  }
  window.closePinDialog = closePinDialog;

  // Confirm pairing (called from the receiving side)
  async function confirmPairing(pin, instanceId) {
    try {
      var r = await fetch('/pairing/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: pin, instance_id: instanceId }),
      });
      var d = await r.json();
      if (d.ok) {
        __toast('Paired with ' + (d.device_name || instanceId));
        closePinDialog();
        refreshPairedDevices();
        refreshPeersList();
        return true;
      }
      __toast(d.error || 'Pairing confirmation failed');
      return false;
    } catch (e) {
      __toast('Confirm error: ' + e.message);
      return false;
    }
  }
  window.confirmPairing = confirmPairing;

  // ── Paired devices list ───────────────────────────────────────────────────

  async function refreshPairedDevices() {
    var list = document.getElementById('paired-devices-list');
    if (!list) return;
    try {
      var r = await fetch('/pairing/paired-devices');
      var devices = await r.json();
      if (!devices || !devices.length) {
        list.innerHTML = '<div class="peers-empty">No paired devices.<br><span style="color:var(--text-dim);font-size:0.75rem">Pair with discovered peers above.</span></div>';
        return;
      }
      var html = devices.map(function (d) {
        var tierLabel = TIER_LABELS[d.hardware_tier] || d.hardware_tier;
        var tierColor = TIER_COLORS[d.hardware_tier] || '#6a6a9a';
        var paired = new Date(d.paired_at * 1000).toLocaleDateString();
        var seen = d.last_seen ? _timeAgo(d.last_seen) : 'unknown';
        var perms = d.permissions || {};
        var permHtml = Object.keys(perms).map(function (k) {
          var label = k.replace(/_/g, ' ');
          var on = !!perms[k];
          return '<label class="perm-toggle' + (on ? ' on' : '') + '">' +
            '<input type="checkbox"' + (on ? ' checked' : '') +
            ' onchange="toggleDevicePermission(\'' + __esc(d.instance_id) + '\',\'' + k + '\',this.checked)">' +
            ' ' + __esc(label) +
          '</label>';
        }).join('');
        return '<div class="paired-device-card">' +
          '<div class="paired-device-header">' +
            '<span class="paired-device-name">' + __esc(d.name) + '</span>' +
            '<span class="paired-device-tier" style="color:' + tierColor + '">' + tierLabel + '</span>' +
          '</div>' +
          '<div class="paired-device-meta">' +
            '<span>Paired: ' + paired + '</span> &middot; <span>Last seen: ' + seen + '</span>' +
          '</div>' +
          '<div class="paired-device-perms">' + permHtml + '</div>' +
          '<div class="paired-device-actions">' +
            '<button class="btn-health" onclick="checkPeerHealth(\'' + __esc(d.instance_id) + '\',this)">Ping</button>' +
            '<button class="btn-unpair" onclick="unpairDevice(\'' + __esc(d.instance_id) + '\',\'' + __esc(d.name) + '\')">Unpair</button>' +
          '</div>' +
        '</div>';
      }).join('');
      list.innerHTML = html;
    } catch (e) {
      list.innerHTML = '<div class="peers-empty">Error: ' + __esc(e.message) + '</div>';
    }
  }
  window.refreshPairedDevices = refreshPairedDevices;

  // ── Permission toggle ─────────────────────────────────────────────────────

  async function toggleDevicePermission(instanceId, key, value) {
    try {
      var body = {};
      body[key] = value;
      await fetch('/pairing/' + encodeURIComponent(instanceId) + '/permissions', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      __toast(key.replace(/_/g, ' ') + ': ' + (value ? 'enabled' : 'disabled'));
    } catch (e) {
      __toast('Permission update failed');
    }
  }
  window.toggleDevicePermission = toggleDevicePermission;

  // ── Unpair ────────────────────────────────────────────────────────────────

  async function unpairDevice(instanceId, name) {
    if (!(await laylaConfirm('Unpair device "' + (name || instanceId) + '"?'))) return;
    try {
      var r = await fetch('/pairing/' + encodeURIComponent(instanceId), { method: 'DELETE' });
      var d = await r.json();
      if (d.ok) {
        __toast('Unpaired: ' + (name || instanceId));
        refreshPairedDevices();
      } else {
        __toast(d.error || 'Unpair failed');
      }
    } catch (e) {
      __toast('Unpair error: ' + e.message);
    }
  }
  window.unpairDevice = unpairDevice;

  // ── Peer health check ─────────────────────────────────────────────────────

  async function checkPeerHealth(instanceId, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    try {
      var r = await fetch('/pairing/peer/' + encodeURIComponent(instanceId) + '/health');
      var d = await r.json();
      if (d.reachable) {
        __toast('Peer reachable (' + d.latency_ms + 'ms)');
        if (btn) { btn.textContent = d.latency_ms + 'ms'; btn.style.color = '#0f0'; }
      } else {
        __toast('Peer unreachable: ' + (d.error || 'timeout'));
        if (btn) { btn.textContent = 'Fail'; btn.style.color = '#f44'; }
      }
    } catch (e) {
      __toast('Health check error');
      if (btn) { btn.textContent = 'Error'; btn.style.color = '#f44'; }
    } finally {
      if (btn) {
        btn.disabled = false;
        setTimeout(function () {
          btn.textContent = 'Ping';
          btn.style.color = '';
        }, 3000);
      }
    }
  }
  window.checkPeerHealth = checkPeerHealth;

  // ── Full panel refresh ────────────────────────────────────────────────────

  async function refreshPeeringPanel() {
    // Update discovery toggle button
    var toggleBtn = document.getElementById('discovery-toggle-btn');
    try {
      var r = await fetch('/pairing/status');
      var status = await r.json();
      _discoveryRunning = status.enabled;
      if (toggleBtn) {
        toggleBtn.textContent = status.enabled ? 'Stop Discovery' : 'Start Discovery';
        toggleBtn.className = status.enabled ? 'btn-discovery active' : 'btn-discovery';
      }
      var idEl = document.getElementById('pairing-instance-id');
      if (idEl) idEl.textContent = status.instance_id || '—';
      var countEl = document.getElementById('pairing-peer-count');
      if (countEl) countEl.textContent = String(status.peer_count || 0);
    } catch (_) {}
    refreshPeersList();
    refreshPairedDevices();
  }
  window.refreshPeeringPanel = refreshPeeringPanel;

  // ── Utility ───────────────────────────────────────────────────────────────

  function _timeAgo(ts) {
    var diff = (Date.now() / 1000) - ts;
    if (diff < 60) return Math.round(diff) + 's ago';
    if (diff < 3600) return Math.round(diff / 60) + 'm ago';
    if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
    return Math.round(diff / 86400) + 'd ago';
  }

  window.laylaPairingModuleLoaded = true;
})();

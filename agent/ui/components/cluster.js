/**
 * components/cluster.js — Cluster status panel logic.
 *
 * Converted from js/layla-cluster.js (IIFE -> ES module).
 * Fetches /cluster/status, /cluster/peers, /cluster/queue/stats
 * and populates the Cluster tab DOM elements.
 */

import { escapeHtml, showToast } from '../services/utils.js';

// ── State ───────────────────────────────────────────────────────────────────
let _refreshing = false;

// ── Helpers ─────────────────────────────────────────────────────────────────
function _esc(s) {
  return escapeHtml(String(s || ''));
}

function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(val != null ? val : '—');
}

function _timeAgo(isoStr) {
  try {
    const d = new Date(isoStr);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return Math.round(diff) + 's ago';
    if (diff < 3600) return Math.round(diff / 60) + 'm ago';
    if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
    return Math.round(diff / 86400) + 'd ago';
  } catch (_) { return ''; }
}

// ── Fetch + populate ────────────────────────────────────────────────────────
export function refreshClusterStatus() {
  if (_refreshing) return;
  _refreshing = true;

  Promise.all([
    fetch('/cluster/status').then(r => r.json()).catch(() => null),
    fetch('/cluster/peers').then(r => r.json()).catch(() => null),
    fetch('/cluster/queue/stats').then(r => r.json()).catch(() => null),
  ])
    .then(([status, peers, queue]) => {
      _refreshing = false;
      _populateCluster(status, peers, queue);
    })
    .catch(e => {
      _refreshing = false;
      console.warn('[Layla Cluster] fetch failed:', e);
    });
}

// ── DOM population ──────────────────────────────────────────────────────────
function _populateCluster(status, peers, queue) {
  // Enabled badge + role — /cluster/status returns `enabled` (not `cluster_enabled`).
  const enabled = status && (status.enabled != null ? status.enabled : status.cluster_enabled);
  const badge = document.getElementById('cluster-enabled-badge');
  if (badge) {
    badge.textContent = enabled ? 'Enabled' : 'Disabled';
    badge.style.background = enabled ? '#2e7d32' : '#666';
  }

  const roleLabel = document.getElementById('cluster-role-label');
  if (roleLabel) {
    const role = (status && status.node_role) || '—';
    roleLabel.textContent = 'Role: ' + role.toUpperCase();
  }

  // Governor mode
  _setText('cluster-governor-mode', _governorMode(status));

  // Peer stats
  const peerList = (peers && peers.peers) || [];
  let onlineCount = 0;
  for (let i = 0; i < peerList.length; i++) {
    if (peerList[i].status === 'online') onlineCount++;
  }
  _setText('cluster-peer-count', String(peerList.length));
  _setText('cluster-online-count', String(onlineCount));

  // Nodes list
  _renderNodes(peerList, status);

  // Queue stats
  _renderQueue(queue);
}

function _governorMode(status) {
  if (!status) return '—';
  if (status.governor_mode) return status.governor_mode.toUpperCase();
  if (status.resource_mode) return status.resource_mode.toUpperCase();
  return '—';
}

function _renderNodes(peers, status) {
  const el = document.getElementById('cluster-nodes-list');
  if (!el) return;

  let html = '';

  // Self node
  if (status) {
    const selfRole = (status.node_role || 'unknown').toUpperCase();
    const selfName = status.node_name || 'This Node';
    html += '<div style="padding:6px 8px;margin-bottom:4px;border-radius:4px;background:rgba(255,255,255,0.06);border-left:3px solid var(--accent)">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center">';
    html += '<span><strong>' + _esc(selfName) + '</strong> <span style="font-size:0.55rem;color:var(--text-dim)">(' + selfRole + ' · self)</span></span>';
    html += '<span style="color:#4caf50;font-size:0.6rem">● online</span>';
    html += '</div>';
    if (status.governor_mode) {
      html += '<div style="font-size:0.55rem;color:var(--text-dim);margin-top:2px">Mode: ' + _esc(status.governor_mode) + '</div>';
    }
    html += '</div>';
  }

  if (!peers.length && !status) {
    el.textContent = 'No nodes connected';
    return;
  }

  // Peer nodes
  for (let i = 0; i < peers.length; i++) {
    const p = peers[i];
    const pName = p.name || p.node_id || 'Unknown';
    const pRole = (p.role || 'drone').toUpperCase();
    const pStatus = p.status || 'offline';
    const dotColor = pStatus === 'online' ? '#4caf50' : pStatus === 'degraded' ? '#ff9800' : '#f44336';

    html += '<div style="padding:6px 8px;margin-bottom:4px;border-radius:4px;background:rgba(255,255,255,0.04)">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center">';
    html += '<span>' + _esc(pName) + ' <span style="font-size:0.55rem;color:var(--text-dim)">(' + pRole + ')</span></span>';
    html += '<span style="color:' + dotColor + ';font-size:0.6rem">● ' + _esc(pStatus) + '</span>';
    html += '</div>';

    const details = [];
    if (p.cpu_pct != null) details.push('CPU ' + Math.round(p.cpu_pct) + '%');
    if (p.ram_pct != null) details.push('RAM ' + Math.round(p.ram_pct) + '%');
    if (p.last_seen) {
      const ago = _timeAgo(p.last_seen);
      if (ago) details.push('seen ' + ago);
    }
    if (details.length) {
      html += '<div style="font-size:0.55rem;color:var(--text-dim);margin-top:2px">' + details.join(' · ') + '</div>';
    }
    html += '</div>';
  }

  el.innerHTML = html || 'No nodes connected';
}

function _renderQueue(queue) {
  const el = document.getElementById('cluster-queue-stats');
  if (!el) return;

  if (!queue || queue.error) {
    el.textContent = 'Queue stats unavailable';
    return;
  }

  const parts = [];
  if (queue.pending != null) parts.push(queue.pending + ' pending');
  if (queue.running != null) parts.push(queue.running + ' running');
  if (queue.completed != null) parts.push(queue.completed + ' completed');
  if (queue.failed != null && queue.failed > 0) parts.push(queue.failed + ' failed');
  if (queue.total != null) parts.push(queue.total + ' total');

  el.textContent = parts.length ? parts.join(' · ') : 'Queue empty';
}

// ── Pairing token generation ────────────────────────────────────────────────
export function generatePairingToken() {
  const tokenEl = document.getElementById('cluster-pairing-token');
  if (!tokenEl) return;

  tokenEl.style.display = 'block';
  tokenEl.innerHTML = '<span style="color:var(--text-dim)">Generating...</span>';

  fetch('/cluster/pair/token')
    .then(r => r.json())
    .then(d => {
      if (d.ok && d.token) {
        const expires = d.expires_in_seconds ? Math.round(d.expires_in_seconds / 60) : 10;
        tokenEl.innerHTML =
          '<div style="margin-bottom:4px;font-size:0.65rem;color:var(--text-dim)">Pairing Token (expires in ' + expires + ' min):</div>' +
          '<div style="font-size:1.1rem;letter-spacing:0.1em;color:var(--accent);user-select:all">' + _esc(d.token) + '</div>' +
          '<div style="margin-top:4px;font-size:0.6rem;color:var(--text-dim)">Share this with the DRONE installer to pair.</div>';
      } else {
        tokenEl.innerHTML = '<span style="color:#f44336">Failed: ' + _esc(d.error || d.detail || 'Unknown error') + '</span>';
      }
    })
    .catch(e => {
      tokenEl.innerHTML = '<span style="color:#f44336">Error: ' + _esc(e.message || String(e)) + '</span>';
    });
}

// ── Enable/Disable toggle ───────────────────────────────────────────────────
/**
 * Turn clustering on or off — through the surface that actually owns the flag.
 *
 * A3, and it was a DEAD CONTROL. This posted {cluster_enabled} to POST /settings.
 * `cluster_enabled` is not in EDITABLE_SCHEMA, so that endpoint drops it and answers
 * HTTP 200 {"ok": false, "rejected": ["cluster_enabled"]} — driven live, exactly that. The
 * handler then read `if (d.ok || d.status === 'ok')` with NO else, so a refusal did nothing
 * at all: no state change, no message, no console line. `.catch` only covers a network
 * failure, so the one path that was actually taken was the one path with no code in it. The
 * user clicked, the switch did not move, and nothing said why.
 *
 * ONE OWNER. The same flag DOES work through POST /settings/themes (the "clustering" feature
 * area, which writes with editable_only=False precisely because cluster_enabled is not
 * individually editable). So the flag had two surfaces and one of them could never work.
 * The themes endpoint is the owner — it already reads the flag back out of the effective
 * config, reports refusals and package gaps, and is what the Settings panel drives. This
 * panel now calls it instead of maintaining a second, broken path to the same flag.
 * POST /settings still refuses `cluster_enabled` and now says so; nothing sends it there.
 *
 * Clustering itself is an unfinished pillar, deliberately kept — this fixes the toggle's
 * HONESTY, not the feature behind it.
 */
export function toggleClusterEnabled() {
  const toggle = document.getElementById('cluster-enable-toggle');
  if (!toggle) return;
  const isActive = toggle.classList.contains('active');
  const newState = !isActive;

  const apply = (on) => {
    toggle.classList.toggle('active', on);
    const droneSection = document.getElementById('cluster-pair-as-drone');
    if (droneSection) droneSection.style.display = on ? 'block' : 'none';
  };

  fetch('/settings/themes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: 'clustering', enabled: newState })
  })
    .then(r => r.json().catch(() => null).then(d => ({ r, d })))
    .then(({ r, d }) => {
      if (!r.ok || !d || !d.ok) {
        // Refused or failed. The switch must stay where the SERVER says it is.
        apply(d && typeof d.enabled === 'boolean' ? d.enabled : isActive);
        showToast('Clustering NOT changed — ' +
          ((d && (d.error || d.detail)) || ('HTTP ' + r.status)));
        refreshClusterStatus();
        return;
      }
      // `d.enabled` is the EFFECTIVE state read back from the running config, not what we
      // asked for. Rendering the request would put the switch in a position the config does
      // not hold — the same lie in a different widget.
      const effective = !!d.enabled;
      apply(effective);
      if (effective !== newState) {
        showToast('Clustering NOT ' + (newState ? 'enabled' : 'disabled') + ' — ' +
          (d.not_in_force_note || 'the running configuration did not take the change'));
        refreshClusterStatus();
        return;
      }
      // THE SETTING IS NOT THE SERVICE. `cluster_enabled` is now true in the running config,
      // and /cluster/status still reports the cluster network as down — it is built at startup
      // and needs a cluster to join. That is not a bug to hide: the badge beside this switch
      // reads "Disabled", and a toast that flatly says "Clustering enabled" next to it just
      // moves the confusion into the operator. Say which of the two actually changed.
      if (effective) {
        fetch('/cluster/status')
          .then(r => r.json())
          .then(st => {
            showToast(st && st.enabled
              ? 'Clustering enabled'
              : 'Clustering enabled in settings — the cluster service is not running yet ' +
                '(no cluster joined; pair with a queen or restart to start it)');
            refreshClusterStatus();
          })
          .catch(() => {
            // Could not confirm the service state, so do not assert either way.
            showToast('Clustering enabled in settings — could not read the cluster service state');
            refreshClusterStatus();
          });
        return;
      }
      showToast('Clustering disabled');
      refreshClusterStatus();
    })
    .catch(e => {
      apply(isActive);
      showToast('Clustering NOT changed — ' + ((e && e.message) || e));
    });
}

// ── Pair as Drone ───────────────────────────────────────────────────────────
export function pairAsDrone() {
  const addr = (document.getElementById('cluster-queen-addr') || {}).value;
  const token = (document.getElementById('cluster-pair-token-input') || {}).value;
  const resultEl = document.getElementById('cluster-pair-result');
  if (!addr || !token) {
    if (resultEl) { resultEl.style.display = 'block'; resultEl.style.color = '#f44336'; resultEl.textContent = 'Both address and token required'; }
    return;
  }
  if (resultEl) { resultEl.style.display = 'block'; resultEl.style.color = 'var(--text-dim)'; resultEl.textContent = 'Pairing...'; }

  fetch('/cluster/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queen_address: addr, token: token })
  })
    .then(r => r.json())
    .then(d => {
      if (resultEl) {
        if (d.ok) {
          resultEl.style.color = '#4caf50';
          resultEl.textContent = 'Paired successfully!';
          refreshClusterStatus();
        } else {
          resultEl.style.color = '#f44336';
          resultEl.textContent = 'Failed: ' + (d.error || d.detail || 'Unknown error');
        }
      }
    })
    .catch(e => {
      if (resultEl) { resultEl.style.color = '#f44336'; resultEl.textContent = 'Error: ' + e.message; }
    });
}

// ── Init ────────────────────────────────────────────────────────────────────
export function initCluster() {
  fetch('/cluster/status')
    .then(r => r.json())
    .then(d => {
      const toggle = document.getElementById('cluster-enable-toggle');
      if (toggle && d && (d.enabled != null ? d.enabled : d.cluster_enabled)) {
        toggle.classList.add('active');
        const droneSection = document.getElementById('cluster-pair-as-drone');
        if (droneSection) droneSection.style.display = 'block';
      }
    })
    .catch(() => {});
}

/**
 * components/sync.js — multi-device sync (W2 BL-043).
 *
 * Surfaces the /sync/* Syncthing backend that had no UI: sync status + peers, this
 * device's ID, a rescan, and the setup guide (shown when sync isn't configured yet).
 * Reuses the overlay shell + G1 tokens; relative fetches. ⌘K → "Sync (devices)".
 */

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
async function _post(url, body) {
  return (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })).json();
}

// BL-386: Escape must work regardless of where focus sits. A listener on _root only fires when the
// keydown target is _root or a descendant; on first-run / just-opened, focus is on <body>, so a _root
// listener never receives it and the "esc" chip advertised an exit that never fired. Listen on
// document (capture), added on open and removed on close so it can never accumulate across opens.
function _onDocKeydown(e) {
  if (!_open) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeSync(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "sync";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Sync");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel sync-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">⇄</span>' +
        '<span class="sysdiag-title">sync</span>' +
        '<button type="button" class="sysdiag-refresh sync-rescan">rescan</button>' +
        '<button type="button" class="sysdiag-refresh sync-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="sync-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeSync(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeSync(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeSync());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeSync(); } });
  }
  _root.querySelector(".sync-refresh").addEventListener("click", _load);
  _root.querySelector(".sync-rescan").addEventListener("click", _rescan);
}

async function _load() {
  const body = _root.querySelector(".sync-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const [status, dev] = await Promise.all([_get("/sync/status"), _get("/sync/device-id")]);
    let html = "";
    if (!status.enabled) {
      html += '<div class="sync-status sync-off">sync is off — not configured</div>';
    } else {
      const state = status.running ? (status.folder_state || "unknown") : "daemon offline";
      html += '<div class="sync-status">status: <b>' + _esc(state) + "</b> · " + Math.round(status.completion || 0) + "% · folder " + _esc(status.folder_id || "") + "</div>";
      const devices = status.devices || [];
      if (devices.length) {
        html += '<div class="sync-devices">' + devices.map((d) =>
          '<div class="sync-device"><span class="sync-dot" data-on="' + (d.connected ? "1" : "0") + '">●</span>' +
          _esc(d.name || d.device_id) + ' <span class="sync-dcomp">' + Math.round(d.completion || 0) + "%</span></div>"
        ).join("") + "</div>";
      }
    }
    if (dev && dev.device_id) {
      html += '<div class="sync-devid"><span class="sync-devid-label">this device</span><code>' + _esc(dev.device_id) + "</code></div>";
    }
    // Setup guide (always useful; primary content when off)
    try {
      const g = await _get("/sync/setup-guide");
      if (g && g.steps) {
        html += '<details class="sync-guide"' + (status.enabled ? "" : " open") + "><summary>" + _esc(g.title || "setup guide") + "</summary><ol>" +
          g.steps.map((s) => "<li><b>" + _esc(s.title) + "</b><div>" + _esc(s.detail) + "</div></li>").join("") + "</ol></details>";
      }
    } catch (_) {}
    body.innerHTML = html || '<div class="sysdiag-muted">no sync info</div>';
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _rescan() {
  try { const r = await _post("/sync/rescan", {}); if (window.showToast) window.showToast(r.ok ? "Rescan triggered" : (r.error || "rescan failed")); } catch (_) {}
}

export function openSync() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeSync() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

/**
 * components/approvals.js — approvals + session grants (W2 BL-049).
 *
 * Surfaces the safety backend that had no UI: pending tool approvals (approve/deny) and
 * the active in-memory session grants (revoke-all). Reuses the overlay shell + G1 tokens;
 * relative fetches (auth via the patched fetch). ⌘K → "Approvals".
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
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeApprovals(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "approvals";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Approvals");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel approvals-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">⚠</span>' +
        '<span class="sysdiag-title">approvals</span>' +
        '<button type="button" class="sysdiag-refresh approvals-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="approvals-body">' +
        '<section class="approvals-sec">' +
          '<div class="approvals-sec-title">' +
            '<span>Pending decisions</span>' +
            '<span class="approvals-count"></span>' +
            '<span style="flex:1"></span>' +
            '<button type="button" class="approvals-denyall" hidden>deny all</button>' +
            '<button type="button" class="approvals-clearpending" hidden>clear all</button>' +
          '</div>' +
          '<div class="approvals-pending"></div>' +
        '</section>' +
        '<section class="approvals-sec"><div class="approvals-sec-title">session grants <button type="button" class="approvals-clear">revoke all</button></div><div class="approvals-grants"></div></section>' +
      "</div>" +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeApprovals(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeApprovals(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeApprovals());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeApprovals(); } });
  }
  _root.querySelector(".approvals-refresh").addEventListener("click", _load);
  _root.querySelector(".approvals-clear").addEventListener("click", _clearGrants);
  _root.querySelector(".approvals-denyall").addEventListener("click", _denyAllPending);
  _root.querySelector(".approvals-clearpending").addEventListener("click", _clearAllPending);
}

// Human-readable one-liner per tool, so a row reads like a decision instead of raw JSON.
function _argSummary(tool, args) {
  if (!args || typeof args !== "object") return "";
  const a = args;
  switch (tool) {
    case "write_file": case "apply_patch": case "search_replace":
      return a.path || a.file || "";
    case "git_commit":
      return a.message ? '"' + String(a.message).slice(0, 60) + '"' : "commit";
    case "run_shell": case "shell": case "run":
      return a.command || a.cmd || "";
    case "mcp_tools_call":
      return (a.server ? a.server + ":" : "") + (a.tool || a.name || "");
    default: {
      const s = JSON.stringify(a);
      return s.length > 80 ? s.slice(0, 80) + "…" : s;
    }
  }
}

const _RISK_COLOR = { high: "#e74c3c", medium: "#f7c94b", low: "#4caf50" };

// Client-side expiry: the backend rejects expired entries on /approve, but /pending
// can still list them until acted on. Drop anything past its expires_at so the panel
// reflects auto-expire immediately.
function _notExpired(p) {
  const exp = p && p.expires_at;
  if (!exp) return true;
  const t = Date.parse(exp);
  return Number.isNaN(t) || t > Date.now();
}

function _load() {
  _loadPending();
  _loadGrants();
}

async function _loadPending() {
  const box = _root.querySelector(".approvals-pending");
  const countEl = _root.querySelector(".approvals-count");
  const denyAllBtn = _root.querySelector(".approvals-denyall");
  const clearBtn = _root.querySelector(".approvals-clearpending");
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/pending");
    const pending = (d.pending || []).filter((p) => (p.status || "pending") === "pending" && _notExpired(p));
    if (countEl) countEl.textContent = pending.length ? String(pending.length) : "";
    if (denyAllBtn) denyAllBtn.hidden = pending.length < 2;
    if (clearBtn) clearBtn.hidden = pending.length < 1;
    if (!pending.length) {
      box.innerHTML = '<div class="approvals-empty">✓ Nothing waiting on you — the agent isn\'t blocked on any approvals.</div>';
      return;
    }
    // Group by tool so N writes/commits collapse into one tidy section instead of a wall.
    const groups = {};
    pending.forEach((p) => { (groups[p.tool || "?"] = groups[p.tool || "?"] || []).push(p); });
    box.innerHTML = Object.keys(groups).sort().map((tool) => {
      const items = groups[tool];
      const rows = items.map((p) => {
        const risk = String(p.risk_level || "").toLowerCase();
        const dot = _RISK_COLOR[risk] ? '<span class="approvals-risk" title="' + _esc(risk) + ' risk" style="background:' + _RISK_COLOR[risk] + '"></span>' : "";
        return '<div class="approvals-item">' +
          '<div class="approvals-item-main">' + dot +
            '<span class="approvals-args" title="' + _esc(JSON.stringify(p.args || {})) + '">' + _esc(_argSummary(tool, p.args) || "—") + '</span>' +
          '</div>' +
          '<div class="approvals-acts">' +
            '<button type="button" class="approvals-yes" data-id="' + _esc(p.id) + '" title="Approve">✓</button>' +
            '<button type="button" class="approvals-no" data-id="' + _esc(p.id) + '" title="Deny">✕</button>' +
          '</div></div>';
      }).join("");
      return '<div class="approvals-group">' +
        '<div class="approvals-group-head"><span class="approvals-tool">' + _esc(tool) + '</span>' +
        '<span class="approvals-group-count">' + items.length + '</span></div>' + rows + '</div>';
    }).join("");
    box.querySelectorAll(".approvals-yes").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), true)));
    box.querySelectorAll(".approvals-no").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), false)));
  } catch (e) {
    box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _clearAllPending() {
  if (!window.confirm("Clear all pending approvals? The agent treats anything unapproved as denied.")) return;
  try { await _post("/pending/clear", {}); if (window.showToast) window.showToast("Cleared pending approvals"); } catch (_) {}
  _loadPending();
}

async function _loadGrants() {
  const box = _root.querySelector(".approvals-grants");
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/session/grants");
    const grants = d.grants || [];
    if (!grants.length) { box.innerHTML = '<div class="sysdiag-muted">no active grants</div>'; return; }
    box.innerHTML = grants.map((g) =>
      '<div class="approvals-grant">' + _esc(g.tool || g.name || JSON.stringify(g).slice(0, 80)) +
      (g.scope ? ' <span class="approvals-gscope">' + _esc(g.scope) + "</span>" : "") + "</div>"
    ).join("");
  } catch (e) {
    box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _decide(id, approve) {
  if (!id) return;
  if (approve && !window.confirm("Approve — this runs the tool. Continue?")) return;
  try { await _post(approve ? "/approve" : "/deny", { id }); } catch (_) {}
  _loadPending();
}

async function _denyAllPending() {
  try {
    const d = await _get("/pending");
    const ids = (d.pending || [])
      .filter((p) => (p.status || "pending") === "pending" && _notExpired(p))
      .map((p) => p.id)
      .filter(Boolean);
    if (!ids.length) { _loadPending(); return; }
    if (!window.confirm("Deny all " + ids.length + " pending approval(s)?")) return;
    await Promise.all(ids.map((id) => _post("/deny", { id }).catch(() => {})));
    if (window.showToast) window.showToast("Denied " + ids.length + " pending approval(s)");
  } catch (_) {}
  _loadPending();
}

async function _clearGrants() {
  if (!window.confirm("Revoke all session grants?")) return;
  try { await _post("/session/grants/clear", {}); if (window.showToast) window.showToast("Session grants revoked"); } catch (_) {}
  _loadGrants();
}

export function openApprovals() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeApprovals() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

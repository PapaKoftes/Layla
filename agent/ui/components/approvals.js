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
        '<section class="approvals-sec"><div class="approvals-sec-title">pending</div><div class="approvals-pending"></div></section>' +
        '<section class="approvals-sec"><div class="approvals-sec-title">session grants <button type="button" class="approvals-clear">revoke all</button></div><div class="approvals-grants"></div></section>' +
      "</div>" +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeApprovals(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeApprovals(); } });
  _root.querySelector(".approvals-refresh").addEventListener("click", _load);
  _root.querySelector(".approvals-clear").addEventListener("click", _clearGrants);
}

function _load() {
  _loadPending();
  _loadGrants();
}

async function _loadPending() {
  const box = _root.querySelector(".approvals-pending");
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/pending");
    const pending = (d.pending || []).filter((p) => (p.status || "pending") === "pending");
    if (!pending.length) { box.innerHTML = '<div class="sysdiag-muted">nothing pending</div>'; return; }
    box.innerHTML = "";
    pending.forEach((p) => {
      const el = document.createElement("div");
      el.className = "approvals-item";
      const args = p.args ? JSON.stringify(p.args).slice(0, 120) : "";
      el.innerHTML =
        '<div class="approvals-item-main"><span class="approvals-tool">' + _esc(p.tool || "?") + "</span>" +
        '<span class="approvals-args">' + _esc(args) + "</span></div>" +
        '<div class="approvals-acts"><button type="button" class="approvals-yes" data-id="' + _esc(p.id) + '">approve</button>' +
        '<button type="button" class="approvals-no" data-id="' + _esc(p.id) + '">deny</button></div>';
      box.appendChild(el);
    });
    box.querySelectorAll(".approvals-yes").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), true)));
    box.querySelectorAll(".approvals-no").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), false)));
  } catch (e) {
    box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
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

async function _clearGrants() {
  if (!window.confirm("Revoke all session grants?")) return;
  try { await _post("/session/grants/clear", {}); if (window.showToast) window.showToast("Session grants revoked"); } catch (_) {}
  _loadGrants();
}

export function openApprovals() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _load();
}

export function closeApprovals() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

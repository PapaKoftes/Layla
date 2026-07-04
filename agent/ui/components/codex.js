/**
 * components/codex.js — relationship codex (W2 BL-044).
 *
 * Surfaces the /codex/* backend that had no UI: the per-workspace relationship codex
 * (entities Layla knows about) and its proposals (generate/approve/dismiss). Every endpoint
 * is workspace-scoped, so the panel carries an editable workspace field (pre-filled from the
 * app's #workspace-path). Reuses the overlay shell + G1 tokens. ⌘K → "Relationship codex".
 */

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
function _ws() { return (_root.querySelector(".codex-ws").value || "").trim(); }
function _q(extra) {
  const p = new URLSearchParams({ workspace_root: _ws() });
  if (extra) for (const k in extra) p.set(k, extra[k]);
  return "?" + p.toString();
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
async function _post(url) { return (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json(); }

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "codex";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Relationship codex");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel codex-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">♡</span>' +
        '<span class="sysdiag-title">relationship codex</span>' +
        '<button type="button" class="sysdiag-refresh codex-gen">generate</button>' +
        '<button type="button" class="sysdiag-refresh codex-load">load</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="codex-wsrow"><input type="text" class="codex-ws" placeholder="workspace path…" /></div>' +
      '<div class="codex-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeCodex(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeCodex(); } });
  _root.querySelector(".codex-load").addEventListener("click", _load);
  _root.querySelector(".codex-gen").addEventListener("click", _generate);
  _root.querySelector(".codex-ws").addEventListener("keydown", (e) => { if (e.key === "Enter") _load(); });
}

async function _load() {
  const body = _root.querySelector(".codex-body");
  if (!_ws()) { body.innerHTML = '<div class="sysdiag-muted">set a workspace path above, then load</div>'; return; }
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const [rel, props] = await Promise.all([_get("/codex/relationship" + _q()), _get("/codex/proposals" + _q())]);
    let html = "";
    const entities = (rel.ok && rel.data && rel.data.entities) || {};
    const names = Object.keys(entities);
    html += '<section class="codex-sec"><div class="codex-sec-title">entities <span class="codex-n">' + names.length + "</span></div>";
    if (!names.length) html += '<div class="sysdiag-muted">' + (rel.ok ? "no entities yet" : _esc(rel.error || "unavailable")) + "</div>";
    else html += names.map((n) => {
      const e = entities[n] || {};
      const sub = e.relationship || e.role || e.notes || (typeof e === "string" ? e : "");
      return '<div class="codex-entity"><span class="codex-ename">' + _esc(n) + "</span>" + (sub ? '<span class="codex-esub">' + _esc(String(sub).slice(0, 80)) + "</span>" : "") + "</div>";
    }).join("");
    html += "</section>";
    const proposals = props.proposals || props.items || (Array.isArray(props) ? props : []);
    html += '<section class="codex-sec"><div class="codex-sec-title">proposals <span class="codex-n">' + proposals.length + "</span></div>";
    if (!proposals.length) html += '<div class="sysdiag-muted">no proposals — hit generate</div>';
    else html += proposals.map((p) =>
      '<div class="codex-prop"><div class="codex-ptext">' + _esc(p.text || p.description || p.summary || JSON.stringify(p).slice(0, 100)) + "</div>" +
      '<div class="codex-pacts"><button type="button" class="codex-yes" data-id="' + _esc(p.id) + '">approve</button>' +
      '<button type="button" class="codex-no" data-id="' + _esc(p.id) + '">dismiss</button></div></div>'
    ).join("");
    html += "</section>";
    body.innerHTML = html;
    body.querySelectorAll(".codex-yes").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), true)));
    body.querySelectorAll(".codex-no").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), false)));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _decide(id, approve) {
  if (id == null) return;
  const url = "/codex/proposals/" + (approve ? "approve" : "dismiss") + _q({ proposal_id: id });
  try { await _post(url); } catch (_) {}
  _load();
}

async function _generate() {
  if (!_ws()) return;
  const body = _root.querySelector(".codex-body");
  body.innerHTML = '<div class="sysdiag-muted">generating…</div>';
  try { await _post("/codex/proposals/generate" + _q()); if (window.showToast) window.showToast("Generated proposals"); } catch (_) {}
  _load();
}

export function openCodex() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  const wsEl = _root.querySelector(".codex-ws");
  if (!wsEl.value) {
    const src = document.getElementById("workspace-path");
    wsEl.value = (src && src.value) || (window.currentWorkspace || "");
  }
  _load();
}

export function closeCodex() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

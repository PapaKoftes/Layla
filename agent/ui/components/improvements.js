/**
 * components/improvements.js — self-improvement proposals (W2 BL-047).
 *
 * Surfaces the /improvements backend that had no UI: Layla's proposed improvements to
 * herself — generate, review, approve, reject. Reuses the overlay shell + G1 tokens;
 * relative fetches (auth via the patched fetch). ⌘K → "Improvements".
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
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeImprovements(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "improvements";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Improvements");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel improvements-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">↑</span>' +
        '<span class="sysdiag-title">improvements</span>' +
        '<button type="button" class="sysdiag-refresh improvements-gen">generate</button>' +
        '<button type="button" class="sysdiag-refresh improvements-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="improvements-list"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeImprovements(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeImprovements(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeImprovements());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeImprovements(); } });
  }
  _root.querySelector(".improvements-refresh").addEventListener("click", _load);
  _root.querySelector(".improvements-gen").addEventListener("click", _generate);
}

function _proposalsFrom(d) {
  if (Array.isArray(d)) return d;
  return d.proposals || d.improvements || d.records || d.items || [];
}

async function _load() {
  const list = _root.querySelector(".improvements-list");
  list.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/improvements?limit=50");
    const props = _proposalsFrom(d);
    if (!props.length) { list.innerHTML = '<div class="sysdiag-muted">no proposals — hit generate</div>'; return; }
    list.innerHTML = "";
    props.forEach((p) => {
      const st = (p.status || "pending").toLowerCase();
      const el = document.createElement("div");
      el.className = "improvements-item";
      const canAct = st === "pending" || st === "proposed" || st === "";
      el.innerHTML =
        '<div class="improvements-head"><span class="improvements-title">' + _esc(p.title || p.kind || p.category || "proposal") + "</span>" +
        '<span class="improvements-status" data-st="' + _esc(st) + '">' + _esc(st) + "</span></div>" +
        '<div class="improvements-desc">' + _esc(p.description || p.rationale || p.detail || "") + "</div>" +
        (canAct ? '<div class="improvements-acts"><button type="button" class="improvements-yes" data-id="' + _esc(p.id) + '">approve</button>' +
          '<button type="button" class="improvements-no" data-id="' + _esc(p.id) + '">reject</button></div>' : "");
      list.appendChild(el);
    });
    list.querySelectorAll(".improvements-yes").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), true)));
    list.querySelectorAll(".improvements-no").forEach((b) => b.addEventListener("click", () => _decide(b.getAttribute("data-id"), false)));
  } catch (e) {
    list.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _decide(id, approve) {
  if (id == null) return;
  const url = approve ? "/improvements/approve_batch" : "/improvements/reject";
  try { await _post(url, { ids: [id] }); } catch (_) {}
  _load();
}

async function _generate() {
  const list = _root.querySelector(".improvements-list");
  list.innerHTML = '<div class="sysdiag-muted">generating…</div>';
  try { await _post("/improvements/generate", {}); if (window.showToast) window.showToast("Generated proposals"); } catch (_) {}
  _load();
}

export function openImprovements() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeImprovements() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

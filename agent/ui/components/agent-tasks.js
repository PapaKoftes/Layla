/**
 * components/agent-tasks.js — background agent tasks (W2 BL-050).
 *
 * Surfaces the /agent/tasks + /agent/background backend that had no UI: start a background
 * agent task, watch the list, cancel a running one. Reuses the overlay shell + G1 tokens;
 * relative fetches. ⌘K → "Background tasks".
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
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeAgentTasks(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "agenttasks";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Background tasks");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel atasks-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">⟳</span>' +
        '<span class="sysdiag-title">background tasks</span>' +
        '<button type="button" class="sysdiag-refresh atasks-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="atasks-create"><input type="text" class="atasks-goal" placeholder="run in background…" />' +
        '<button type="button" class="atasks-start setup-btn primary">start</button></div>' +
      '<div class="atasks-list"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeAgentTasks(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeAgentTasks(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeAgentTasks());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeAgentTasks(); } });
  }
  _root.querySelector(".atasks-refresh").addEventListener("click", _load);
  _root.querySelector(".atasks-start").addEventListener("click", _create);
  _root.querySelector(".atasks-goal").addEventListener("keydown", (e) => { if (e.key === "Enter") _create(); });
}

const _ACTIVE = new Set(["queued", "running", "pending", "paused"]);

async function _load() {
  const list = _root.querySelector(".atasks-list");
  list.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/agent/tasks");
    const tasks = d.tasks || [];
    if (!tasks.length) { list.innerHTML = '<div class="sysdiag-muted">no background tasks</div>'; return; }
    list.innerHTML = "";
    tasks.forEach((t) => {
      const st = (t.status || "").toLowerCase();
      const el = document.createElement("div");
      el.className = "atasks-item";
      el.innerHTML =
        '<div class="atasks-main"><span class="atasks-goaltxt">' + _esc(t.goal || t.task_id) + "</span>" +
        '<span class="atasks-meta"><span class="atasks-status" data-st="' + _esc(st) + '">' + _esc(st || "?") + "</span>" +
        (t.kind ? ' · ' + _esc(t.kind) : "") + "</span></div>" +
        (_ACTIVE.has(st) ? '<button type="button" class="atasks-cancel" data-id="' + _esc(t.task_id) + '">cancel</button>' : "");
      list.appendChild(el);
    });
    list.querySelectorAll(".atasks-cancel").forEach((b) => b.addEventListener("click", () => _cancel(b.getAttribute("data-id"))));
  } catch (e) {
    list.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _create() {
  const inp = _root.querySelector(".atasks-goal");
  const goal = (inp.value || "").trim();
  if (!goal) return;
  inp.value = "";
  try { await _post("/agent/background", { goal }); if (window.showToast) window.showToast("Background task started"); } catch (_) {}
  _load();
}

async function _cancel(id) {
  if (!id) return;
  try { await _post("/agent/tasks/" + encodeURIComponent(id) + "/cancel", {}); } catch (_) {}
  _load();
}

export function openAgentTasks() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeAgentTasks() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

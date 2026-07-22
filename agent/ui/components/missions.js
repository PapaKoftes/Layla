/**
 * components/missions.js — missions board (W2 BL-041).
 *
 * Surfaces the /missions/* backend that had no UI: start a mission, see it flow across
 * status columns, and pause/resume/cancel it. Reuses the overlay shell + G1 tokens;
 * relative fetches (auth via the patched fetch). Opened from ⌘K → "Missions".
 */

let _root = null;
let _open = false;

const _COLS = [
  { key: "running", label: "running", statuses: ["running"] },
  { key: "paused", label: "paused", statuses: ["paused"] },
  { key: "pending", label: "queued", statuses: ["pending"] },
  { key: "done", label: "done", statuses: ["completed", "failed"] },
];

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function _get(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  return r.json();
}
async function _post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return r.json();
}

// BL-386: Escape must work regardless of where focus sits. A listener on _root only fires when the
// keydown target is _root or a descendant; on first-run / just-opened, focus is on <body>, so a _root
// listener never receives it and the "esc" chip advertised an exit that never fired. Listen on
// document (capture), added on open and removed on close so it can never accumulate across opens.
function _onDocKeydown(e) {
  if (!_open) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMissions(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "missions";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Missions");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel missions-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">◇</span>' +
        '<span class="sysdiag-title">missions</span>' +
        '<button type="button" class="sysdiag-refresh missions-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="missions-create">' +
        '<input type="text" class="missions-goal" placeholder="new mission goal…" />' +
        '<button type="button" class="missions-start setup-btn primary">start</button></div>' +
      '<div class="missions-board"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeMissions(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeMissions(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeMissions());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeMissions(); } });
  }
  _root.querySelector(".missions-refresh").addEventListener("click", _load);
  _root.querySelector(".missions-start").addEventListener("click", _create);
  _root.querySelector(".missions-goal").addEventListener("keydown", (e) => { if (e.key === "Enter") _create(); });
}

function _mid(m) { return m.id || m.mission_id || ""; }

function _actionsFor(status) {
  if (status === "running") return [["pause", "pause"], ["cancel", "cancel"]];
  if (status === "paused") return [["resume", "resume"], ["cancel", "cancel"]];
  if (status === "pending") return [["cancel", "cancel"]];
  return [];
}

function _render(missions) {
  const board = _root.querySelector(".missions-board");
  board.innerHTML = "";
  if (!missions.length) { board.innerHTML = '<div class="sysdiag-muted">no missions yet — start one above</div>'; return; }
  _COLS.forEach((col) => {
    const items = missions.filter((m) => col.statuses.includes((m.status || "").toLowerCase()));
    const colEl = document.createElement("div");
    colEl.className = "missions-col";
    colEl.innerHTML = '<div class="missions-col-title">' + col.label + " <span class=\"missions-col-n\">" + items.length + "</span></div>";
    items.forEach((m) => {
      const card = document.createElement("div");
      card.className = "missions-card";
      const acts = _actionsFor((m.status || "").toLowerCase())
        .map(([lbl, a]) => '<button type="button" data-a="' + a + '" data-id="' + _esc(_mid(m)) + '">' + lbl + "</button>").join("");
      card.innerHTML =
        '<div class="missions-goal-txt">' + _esc(m.goal || m.title || _mid(m)) + "</div>" +
        (acts ? '<div class="missions-acts">' + acts + "</div>" : "");
      colEl.appendChild(card);
    });
    board.appendChild(colEl);
  });
  board.querySelectorAll(".missions-acts button").forEach((b) =>
    b.addEventListener("click", () => _act(b.getAttribute("data-id"), b.getAttribute("data-a"))));
}

async function _load() {
  const board = _root.querySelector(".missions-board");
  board.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/missions?limit=100");
    _render(d.missions || []);
  } catch (e) {
    board.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _create() {
  const inp = _root.querySelector(".missions-goal");
  const goal = (inp.value || "").trim();
  if (!goal) return;
  inp.value = "";
  try {
    await _post("/mission", { goal });
    if (window.showToast) window.showToast("Mission started");
  } catch (_) {}
  _load();
}

async function _act(id, action) {
  if (!id) return;
  if (action === "cancel" && !window.confirm("Cancel this mission?")) return;
  try { await _post("/mission/" + encodeURIComponent(id) + "/" + action, {}); } catch (_) {}
  _load();
}

export function openMissions() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeMissions() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

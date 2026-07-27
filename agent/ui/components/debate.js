/**
 * components/debate.js — multi-aspect deliberation (W2 BL-048).
 *
 * Surfaces the /debate backend that had no UI: pose a question, pick a mode (solo/debate/
 * council/tribunal), and see the aspects deliberate → a synthesized answer. Reuses the
 * overlay shell + G1 tokens; relative fetches. ⌘K → "Deliberate".
 */

let _root = null;
let _open = false;
let _modes = [];
let _mode = "auto";

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
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeDebate(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "debate";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Deliberate");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel debate-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">⚖</span>' +
        '<span class="sysdiag-title">deliberate</span><kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="debate-body">' +
        '<div class="debate-modes"></div>' +
        '<textarea class="debate-goal" rows="2" placeholder="a question worth deliberating…"></textarea>' +
        '<div class="debate-actions"><button type="button" class="debate-run setup-btn primary">deliberate</button>' +
        '<span class="debate-note"></span></div>' +
        '<div class="debate-result"></div>' +
      "</div>" +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeDebate(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeDebate(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeDebate());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeDebate(); } });
  }
  _root.querySelector(".debate-run").addEventListener("click", _run);
}

function _renderModes() {
  const wrap = _root.querySelector(".debate-modes");
  const opts = [{ id: "auto", label: "Auto", description: "Layla picks the mode." }].concat(_modes);
  wrap.innerHTML = opts.map((mo) =>
    '<button type="button" class="debate-mode' + (mo.id === _mode ? " is-sel" : "") + '" data-id="' + _esc(mo.id) + '" title="' + _esc(mo.description || "") + '">' +
    _esc(mo.label || mo.id) + (mo.aspects ? ' <span class="debate-mode-n">' + mo.aspects + "</span>" : "") + "</button>"
  ).join("");
  wrap.querySelectorAll(".debate-mode").forEach((b) => b.addEventListener("click", () => {
    _mode = b.getAttribute("data-id");
    wrap.querySelectorAll(".debate-mode").forEach((x) => x.classList.toggle("is-sel", x === b));
  }));
}

async function _run() {
  const goal = (_root.querySelector(".debate-goal").value || "").trim();
  const note = _root.querySelector(".debate-note");
  const out = _root.querySelector(".debate-result");
  if (!goal) { note.textContent = "type a question first"; return; }
  note.textContent = "deliberating… (this runs the model)";
  out.innerHTML = "";
  try {
    const d = await _post("/debate", { goal, mode: _mode });
    note.textContent = "";
    if (d.ok === false) throw new Error(d.error || "failed");
    const parts = (d.participating_aspects || []).join(", ");
    out.innerHTML =
      '<div class="debate-meta">mode: ' + _esc(d.mode || _mode) + (parts ? " · " + _esc(parts) : "") + "</div>" +
      '<div class="debate-final">' + _esc(d.final_response || "") + "</div>";
  } catch (e) {
    note.textContent = "error — " + _esc(e.message || e);
  }
}

export async function openDebate() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  if (!_modes.length) {
    try { const d = await _get("/debate/modes"); _modes = d.modes || []; } catch (_) { _modes = []; }
  }
  _renderModes();
}

export function closeDebate() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

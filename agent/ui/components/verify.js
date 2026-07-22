/**
 * components/verify.js — verify-what-Layla-learned loop (W2 BL-052).
 *
 * Surfaces the /verify/* queue that had no UI: step through facts Layla is unsure about,
 * confirm or correct them (the "it learns" loop). Reuses the overlay shell + G1 tokens;
 * relative fetches. ⌘K → "Verify learnings".
 */

let _root = null;
let _open = false;
let _fact = null;

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
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeVerify(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "verify";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Verify learnings");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel verify-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">✓?</span>' +
        '<span class="sysdiag-title">verify learnings</span>' +
        '<span class="verify-stats"></span>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="verify-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeVerify(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeVerify(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeVerify());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeVerify(); } });
  }
}

function _factText(f) {
  if (!f) return "";
  return f.content || f.question || f.text || f.fact || f.prompt || (typeof f === "string" ? f : JSON.stringify(f).slice(0, 160));
}
function _factId(f) { return (f && (f.fact_id || f.id)) || ""; }

async function _refreshStats() {
  try {
    const s = await _get("/verify/stats");
    const el = _root.querySelector(".verify-stats");
    if (el) el.textContent = s.ok !== false ? (s.pending ?? s.queue_size ?? s.total ?? 0) + " pending" : "";
  } catch (_) {}
}

async function _next() {
  const body = _root.querySelector(".verify-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  _refreshStats();
  try {
    const d = await _get("/verify/next");
    _fact = d.fact || null;
    if (!_fact) { body.innerHTML = '<div class="german-ok">✓ nothing to verify — you’re caught up</div>'; return; }
    body.innerHTML =
      '<div class="verify-q">is this right?</div>' +
      '<div class="verify-fact">' + _esc(_factText(_fact)) + "</div>" +
      '<div class="verify-acts"><button type="button" class="verify-yes">yes ✓</button>' +
      '<button type="button" class="verify-fix">no / correct</button></div>' +
      '<div class="verify-correct" hidden><textarea class="verify-correction" rows="2" placeholder="the correct version…"></textarea>' +
      '<button type="button" class="verify-savefix setup-btn primary">save correction</button></div>';
    body.querySelector(".verify-yes").addEventListener("click", () => _answer(true, ""));
    body.querySelector(".verify-fix").addEventListener("click", () => { body.querySelector(".verify-correct").hidden = false; body.querySelector(".verify-correction").focus(); });
    body.querySelector(".verify-savefix").addEventListener("click", () => _answer(false, (body.querySelector(".verify-correction").value || "").trim()));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _answer(confirmed, correction) {
  const id = _factId(_fact);
  if (!id) return;
  try { await _post("/verify/answer", { fact_id: id, confirmed, correction }); } catch (_) {}
  _next();
}

export function openVerify() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _next();
}

export function closeVerify() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

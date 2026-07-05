/**
 * components/tutor.js — generalized multi-language tutor (BL-220).
 *
 * The German tutor, generalized: pick a language (German/Italian/Spanish/…) and the same panel
 * teaches it — check-my-writing (LLM correction), flashcard SRS, CEFR level, placement quiz — all
 * via the language-parametrized /language/{lang}/* API. ⌘K → "Language tutor".
 */

let _root = null;
let _open = false;
let _lang = "german";
const _fc = { queue: [], idx: 0, revealed: false, reviewed: 0 };
const _LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];

function _esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
async function _get(u) { return (await fetch(u, { headers: { Accept: "application/json" } })).json(); }
async function _post(u, b) { return (await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) })).json(); }
const _api = (path) => "/language/" + encodeURIComponent(_lang) + path;

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "tutor";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Language tutor");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel german-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon tutor-flag" aria-hidden="true">🌐</span>' +
        '<span class="sysdiag-title">language tutor</span>' +
        '<label class="german-level tutor-langwrap">lang <select class="tutor-lang-sel"></select></label>' +
        '<label class="german-level">level <select class="german-level-sel">' +
          _LEVELS.map((l) => "<option>" + l + "</option>").join("") + "</select></label>" +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="german-body">' +
        '<section class="german-sec"><div class="german-sec-title tutor-checktitle">check my writing</div>' +
          '<textarea class="german-input" rows="3" placeholder="type or paste…" spellcheck="false"></textarea>' +
          '<div class="german-actions"><button type="button" class="german-check setup-btn primary">check</button></div>' +
          '<div class="german-result"></div></section>' +
        '<section class="german-sec"><div class="german-sec-title">flashcards <span class="german-fc-stats"></span></div>' +
          '<div class="german-fc"></div>' +
          '<div class="german-actions"><button type="button" class="german-fc-start setup-btn">review due</button>' +
            '<button type="button" class="tutor-fc-add setup-btn">+ add card</button></div>' +
          '<div class="tutor-add" hidden><input type="text" class="tutor-front" placeholder="front (word/phrase)" />' +
            '<input type="text" class="tutor-back" placeholder="back (meaning)" />' +
            '<button type="button" class="tutor-save setup-btn primary">save</button></div></section>' +
        '<section class="german-sec"><div class="german-sec-title">find my level</div>' +
          '<div class="german-cal"></div>' +
          '<div class="german-actions"><button type="button" class="german-cal-start setup-btn">start placement</button></div></section>' +
      "</div></div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeTutor(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeTutor(); } });
  _root.querySelector(".german-check").addEventListener("click", _check);
  _root.querySelector(".german-fc-start").addEventListener("click", _startReview);
  _root.querySelector(".german-cal-start").addEventListener("click", _startCalibration);
  _root.querySelector(".tutor-fc-add").addEventListener("click", () => { const a = _root.querySelector(".tutor-add"); a.hidden = !a.hidden; });
  _root.querySelector(".tutor-save").addEventListener("click", _addCard);
  _root.querySelector(".german-level-sel").addEventListener("change", (e) => _setLevel(e.target.value));
  _root.querySelector(".tutor-lang-sel").addEventListener("change", (e) => { _lang = e.target.value; _onLangChange(); });
}

async function _loadLanguages() {
  try {
    const d = await _get("/language/languages");
    const sel = _root.querySelector(".tutor-lang-sel");
    sel.innerHTML = (d.languages || []).map((l) =>
      '<option value="' + _esc(l.code) + '"' + (l.code === _lang ? " selected" : "") + ">" + _esc((l.flag || "") + " " + l.name) + "</option>").join("");
  } catch (_) {}
}

function _onLangChange() {
  const name = (_root.querySelector(".tutor-lang-sel").selectedOptions[0] || {}).textContent || _lang;
  _root.querySelector(".tutor-checktitle").textContent = "check my " + name.replace(/^[^\sA-Za-z]+\s*/, "").toLowerCase();
  _root.querySelector(".german-input").value = "";
  _root.querySelector(".german-result").innerHTML = "";
  _root.querySelector(".german-fc").innerHTML = "";
  _root.querySelector(".german-cal").innerHTML = "";
  _loadProfile();
  _refreshStats();
}

async function _loadProfile() {
  try {
    const p = await _get(_api("/profile"));
    const sel = _root.querySelector(".german-level-sel");
    if (sel && p.level) sel.value = p.level;
  } catch (_) {}
}

async function _setLevel(level) { try { await _post(_api("/level"), { level }); } catch (_) {} }

async function _check() {
  const ta = _root.querySelector(".german-input");
  const out = _root.querySelector(".german-result");
  const text = (ta.value || "").trim();
  if (!text) { out.innerHTML = '<div class="sysdiag-muted">type something first</div>'; return; }
  out.innerHTML = '<div class="sysdiag-muted">checking…</div>';
  try {
    const d = await _post(_api("/correct"), { text });
    if (d.ok === false) throw new Error(d.error || "failed");
    const errs = d.errors || [];
    if (!errs.length) { out.innerHTML = '<div class="german-ok">✓ looks good — no issues found' + (d.level ? " · level " + _esc(d.level) : "") + "</div>"; return; }
    out.innerHTML =
      '<div class="german-errcount">' + errs.length + " issue" + (errs.length === 1 ? "" : "s") + "</div>" +
      (d.corrected ? '<div class="tutor-corrected">→ ' + _esc(d.corrected) + "</div>" : "") +
      '<ul class="german-errs">' + errs.map((e) =>
        '<li><span class="german-err-match">' + _esc(e.match ?? "") + '</span> → <span class="german-err-hint">' + _esc(e.hint ?? "") + "</span></li>").join("") + "</ul>";
  } catch (e) { out.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>"; }
}

async function _refreshStats() {
  try { const s = await _get(_api("/flashcards/stats")); const el = _root.querySelector(".german-fc-stats"); if (el) el.textContent = s.ok !== false ? "(" + (s.due ?? 0) + " due · " + (s.total ?? 0) + " total)" : ""; } catch (_) {}
}

async function _addCard() {
  const f = _root.querySelector(".tutor-front"), b = _root.querySelector(".tutor-back");
  const front = (f.value || "").trim(), back = (b.value || "").trim();
  if (!front || !back) return;
  try { await _post(_api("/flashcards"), { front, back }); f.value = ""; b.value = ""; if (window.showToast) window.showToast("Card added"); _refreshStats(); } catch (_) {}
}

async function _startReview() {
  const box = _root.querySelector(".german-fc");
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get(_api("/flashcards/due"));
    _fc.queue = d.cards || []; _fc.idx = 0; _fc.revealed = false; _fc.reviewed = 0;
    if (!_fc.queue.length) { box.innerHTML = '<div class="german-ok">✓ nothing due — you’re caught up</div>'; return; }
    _renderCard();
  } catch (e) { box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>"; }
}

function _renderCard() {
  const box = _root.querySelector(".german-fc");
  const card = _fc.queue[_fc.idx];
  if (!card) { box.innerHTML = '<div class="german-ok">✓ done — ' + _fc.reviewed + " reviewed</div>"; _refreshStats(); return; }
  box.innerHTML =
    '<div class="german-card"><div class="german-card-front">' + _esc(card.front) + "</div>" +
    (_fc.revealed ? '<div class="german-card-back">' + _esc(card.back) + "</div>" : "") +
    '<div class="german-card-actions">' +
      (_fc.revealed
        ? '<button type="button" data-q="1">again</button><button type="button" data-q="3">hard</button><button type="button" data-q="5">good</button>'
        : '<button type="button" class="tutor-reveal">reveal</button>') + "</div></div>";
  if (_fc.revealed) box.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => _grade(card.id, parseInt(b.getAttribute("data-q"), 10))));
  else box.querySelector(".tutor-reveal").addEventListener("click", () => { _fc.revealed = true; _renderCard(); });
}

async function _grade(id, q) {
  try { await _post(_api("/flashcards/" + id + "/review"), { quality: q }); } catch (_) {}
  _fc.reviewed++; _fc.idx++; _fc.revealed = false; _renderCard();
}

const _CAL_LEVELS = ["A1", "A2", "B1", "B2"];
async function _startCalibration() {
  const box = _root.querySelector(".german-cal");
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const byLevel = await Promise.all(_CAL_LEVELS.map(async (lv) => { const d = await _get(_api("/calibrate/" + lv)); return { level: lv, sentences: (d && d.sentences) || [] }; }));
    box.innerHTML = byLevel.map((g) =>
      '<div class="german-cal-lv" data-level="' + g.level + '"><div class="german-cal-head"><span class="german-cal-badge">' + _esc(g.level) + "</span>" +
      '<span class="german-cal-q">how much did you understand?</span><select class="german-cal-score">' +
      [0, 1, 2, 3, 4, 5].map((n) => '<option value="' + n + '"' + (n === 3 ? " selected" : "") + ">" + n + "</option>").join("") + "</select></div>" +
      '<ul class="german-cal-sents">' + g.sentences.slice(0, 3).map((s) => "<li>" + _esc(typeof s === "string" ? s : (s.text || JSON.stringify(s))) + "</li>").join("") + "</ul></div>"
    ).join("") + '<div class="german-actions"><button type="button" class="german-cal-submit setup-btn primary">get my level</button></div><div class="german-cal-result"></div>';
    box.querySelector(".german-cal-submit").addEventListener("click", _submitCalibration);
  } catch (e) { box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>"; }
}

async function _submitCalibration() {
  const box = _root.querySelector(".german-cal");
  const answers = [...box.querySelectorAll(".german-cal-lv")].map((el) => ({ level: el.getAttribute("data-level"), score: parseInt(el.querySelector(".german-cal-score").value, 10) || 0 }));
  const res = box.querySelector(".german-cal-result");
  res.innerHTML = '<div class="sysdiag-muted">scoring…</div>';
  try {
    const d = await _post(_api("/calibrate"), { answers });
    if (d.ok === false) throw new Error(d.error || "failed");
    const lvl = d.recommended_level || d.level || "";
    res.innerHTML = lvl ? '<div class="german-ok">recommended level: <strong>' + _esc(lvl) + "</strong></div>" : "";
    const sel = _root.querySelector(".german-level-sel");
    if (lvl && sel) { sel.value = lvl; }
  } catch (e) { res.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>"; }
}

export function openTutor() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _loadLanguages().then(() => { _onLangChange(); });
}

export function closeTutor() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

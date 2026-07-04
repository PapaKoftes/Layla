/**
 * components/intake-quiz.js — S.P.E.C.I.A.L.-style operator intake quiz (W3 BL-093 / REQ-80).
 *
 * Surfaces the /operator/quiz backend that had no UI: scenario questions across stages →
 * a scored identity preview (stats/prefs) you can save. Single-select per question; advances
 * stage-by-stage until the backend reports no more stages, then submits for a preview.
 * Overlay shell + G1 tokens; relative fetches. ⌘K → "Intake quiz".
 */

let _root = null;
let _open = false;
let _stage = 0;
const _answers = {}; // question_id -> option_id

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
  _root.id = "intakequiz";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Intake quiz");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel quiz-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">✶</span>' +
        '<span class="sysdiag-title">intake quiz</span>' +
        '<span class="quiz-progress"></span>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="quiz-body"></div>' +
      '<div class="quiz-foot">' +
        '<button type="button" class="quiz-back sysdiag-refresh" hidden>back</button>' +
        '<span class="quiz-note"></span>' +
        '<button type="button" class="quiz-next setup-btn primary">continue</button>' +
      "</div>" +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeIntakeQuiz(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeIntakeQuiz(); } });
  _root.querySelector(".quiz-back").addEventListener("click", () => { if (_stage > 0) { _stage--; _loadStage(); } });
  _root.querySelector(".quiz-next").addEventListener("click", _onNext);
}

async function _loadStage() {
  const body = _root.querySelector(".quiz-body");
  const back = _root.querySelector(".quiz-back");
  const next = _root.querySelector(".quiz-next");
  const prog = _root.querySelector(".quiz-progress");
  _root.querySelector(".quiz-note").textContent = "";
  back.hidden = _stage === 0;
  next.textContent = "continue";
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/operator/quiz/stage/" + _stage);
    if (!d || d.ok === false) { return _renderFinish(); }  // no more stages → finish
    const qs = d.questions || [];
    if (!qs.length) { return _renderFinish(); }
    if (prog) prog.textContent = "stage " + (_stage + 1);
    body.innerHTML = qs.map((q) =>
      '<div class="quiz-q" data-qid="' + _esc(q.id) + '">' +
      '<div class="quiz-prompt">' + _esc(q.prompt) + "</div>" +
      '<div class="quiz-opts">' + (q.options || []).map((o) =>
        '<button type="button" class="quiz-opt' + (_answers[q.id] === o.id ? " is-sel" : "") + '" data-oid="' + _esc(o.id) + '">' + _esc(o.label) + "</button>"
      ).join("") + "</div></div>"
    ).join("");
    body.querySelectorAll(".quiz-q").forEach((qEl) => {
      const qid = qEl.getAttribute("data-qid");
      qEl.querySelectorAll(".quiz-opt").forEach((b) => b.addEventListener("click", () => {
        _answers[qid] = b.getAttribute("data-oid");
        qEl.querySelectorAll(".quiz-opt").forEach((x) => x.classList.remove("is-sel"));
        b.classList.add("is-sel");
      }));
    });
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

function _stageAnswered() {
  const qs = [..._root.querySelectorAll(".quiz-q")];
  return qs.length > 0 && qs.every((q) => _answers[q.getAttribute("data-qid")]);
}

async function _onNext() {
  // On the finish screen the button says "save & finish".
  if (_root.querySelector(".quiz-preview")) { return _submit(true); }
  if (!_stageAnswered()) { _root.querySelector(".quiz-note").textContent = "answer every question"; return; }
  _stage++;
  _loadStage();
}

function _answersList() {
  return Object.keys(_answers).map((qid) => ({ question_id: qid, option_id: _answers[qid] }));
}

async function _renderFinish() {
  const body = _root.querySelector(".quiz-body");
  const back = _root.querySelector(".quiz-back");
  const next = _root.querySelector(".quiz-next");
  const prog = _root.querySelector(".quiz-progress");
  if (prog) prog.textContent = "review";
  back.hidden = false;
  next.textContent = "save & finish";
  body.innerHTML = '<div class="sysdiag-muted">scoring…</div>';
  try {
    const d = await _post("/operator/quiz/submit", { answers: _answersList(), finalize: false });
    const preview = (d && d.preview) || {};
    const stats = preview.stats || preview.stat_ids || preview;
    let rows = "";
    if (stats && typeof stats === "object") {
      rows = Object.keys(stats).filter((k) => typeof stats[k] === "number").map((k) => {
        const v = Math.max(0, Math.min(10, Number(stats[k])));
        return '<div class="quiz-stat"><span class="quiz-statname">' + _esc(k) + "</span>" +
          '<span class="quiz-bar"><span class="quiz-fill" style="width:' + (v * 10) + '%"></span></span>' +
          '<span class="quiz-statval">' + _esc(v) + "</span></div>";
      }).join("");
    }
    body.innerHTML =
      '<div class="quiz-preview"><div class="quiz-prompt">your profile</div>' +
      (rows || '<div class="sysdiag-muted">' + _esc(JSON.stringify(preview).slice(0, 400)) + "</div>") +
      "</div>";
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _submit(finalize) {
  const note = _root.querySelector(".quiz-note");
  note.textContent = "saving…";
  try {
    const d = await _post("/operator/quiz/submit", { answers: _answersList(), finalize: !!finalize });
    if (d && d.ok) {
      note.textContent = "✓ saved";
      note.setAttribute("data-ok", "true");
      if (window.showToast) window.showToast("Profile saved");
      setTimeout(closeIntakeQuiz, 1000);
    } else {
      note.textContent = "error — " + ((d && d.error) || "save failed");
    }
  } catch (e) {
    note.textContent = "error — " + (e && e.message ? e.message : e);
  }
}

export function openIntakeQuiz() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _stage = 0;
  for (const k in _answers) delete _answers[k];
  _loadStage();
}

export function closeIntakeQuiz() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

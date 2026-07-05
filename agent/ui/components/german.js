/**
 * components/german.js — German language-learning panel (W2 BL-040, the headline wedge).
 *
 * Surfaces the fully-built /german/* backend that had no UI: check-my-German (corrections)
 * and flashcard review (SRS), plus the CEFR level. Reuses the overlay shell + G1 tokens;
 * relative fetches (auth via the patched fetch). Opened from ⌘K → "German".
 */

let _root = null;
let _open = false;
const _fc = { queue: [], idx: 0, revealed: false, reviewed: 0 };

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

async function _get(url) {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  return r.json();
}
async function _post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  return r.json();
}

const _LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];

function _build() {
  if (_root) return;
  _root = document.createElement('div');
  _root.id = 'german';
  _root.className = 'cmdp-backdrop sysdiag-backdrop';
  _root.setAttribute('role', 'dialog');
  _root.setAttribute('aria-modal', 'true');
  _root.setAttribute('aria-label', 'German learning');
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel german-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">DE</span>' +
        '<span class="sysdiag-title">german</span>' +
        '<label class="german-level">level ' +
          '<select class="german-level-sel">' + _LEVELS.map((l) => '<option>' + l + '</option>').join('') + '</select>' +
        '</label>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="german-body">' +
        '<section class="german-sec">' +
          '<div class="german-sec-title">check my german</div>' +
          '<textarea class="german-input" rows="3" placeholder="type or paste German…" spellcheck="false"></textarea>' +
          '<div class="german-actions"><button type="button" class="german-check setup-btn primary">check</button></div>' +
          '<div class="german-result"></div>' +
        '</section>' +
        '<section class="german-sec">' +
          '<div class="german-sec-title">flashcards <span class="german-fc-stats"></span></div>' +
          '<div class="german-fc"></div>' +
          '<div class="german-actions"><button type="button" class="german-fc-start setup-btn">review due</button></div>' +
        '</section>' +
        '<section class="german-sec">' +
          '<div class="german-sec-title">correction history</div>' +
          '<div class="german-hist"></div>' +
          '<div class="german-actions"><button type="button" class="german-hist-load setup-btn">show recent</button></div>' +
        '</section>' +
        '<section class="german-sec">' +
          '<div class="german-sec-title">find my level</div>' +
          '<div class="german-cal"></div>' +
          '<div class="german-actions"><button type="button" class="german-cal-start setup-btn">start placement</button></div>' +
        '</section>' +
      '</div>' +
    '</div>';
  document.body.appendChild(_root);
  _root.addEventListener('mousedown', (e) => { if (e.target === _root) closeGerman(); });
  _root.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closeGerman(); } });
  _root.querySelector('.german-check').addEventListener('click', _check);
  _root.querySelector('.german-fc-start').addEventListener('click', _startReview);
  _root.querySelector('.german-hist-load').addEventListener('click', _loadCorrections);
  _root.querySelector('.german-cal-start').addEventListener('click', _startCalibration);
  _root.querySelector('.german-level-sel').addEventListener('change', (e) => _setLevel(e.target.value));
}

const _CAL_LEVELS = ['A1', 'A2', 'B1', 'B2'];

async function _startCalibration() {
  const box = _root.querySelector('.german-cal');
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const byLevel = await Promise.all(_CAL_LEVELS.map(async (lv) => {
      const d = await _get('/german/calibrate/' + lv);
      return { level: lv, sentences: (d && d.sentences) || [] };
    }));
    box.innerHTML = byLevel.map((g) =>
      '<div class="german-cal-lv" data-level="' + g.level + '">' +
      '<div class="german-cal-head"><span class="german-cal-badge">' + _esc(g.level) + '</span>' +
      '<span class="german-cal-q">how much did you understand?</span>' +
      '<select class="german-cal-score">' + [0, 1, 2, 3, 4, 5].map((n) =>
        '<option value="' + n + '"' + (n === 3 ? ' selected' : '') + '>' + n + '</option>').join('') + '</select></div>' +
      '<ul class="german-cal-sents">' + g.sentences.slice(0, 3).map((s) =>
        '<li>' + _esc(typeof s === 'string' ? s : (s.text || s.sentence || JSON.stringify(s))) + '</li>').join('') + '</ul></div>'
    ).join('') + '<div class="german-actions"><button type="button" class="german-cal-submit setup-btn primary">get my level</button></div><div class="german-cal-result"></div>';
    box.querySelector('.german-cal-submit').addEventListener('click', _submitCalibration);
  } catch (e) {
    box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + '</div>';
  }
}

async function _submitCalibration() {
  const box = _root.querySelector('.german-cal');
  const answers = [...box.querySelectorAll('.german-cal-lv')].map((el) => ({
    level: el.getAttribute('data-level'),
    score: parseInt(el.querySelector('.german-cal-score').value, 10) || 0,
  }));
  const res = box.querySelector('.german-cal-result');
  res.innerHTML = '<div class="sysdiag-muted">scoring…</div>';
  try {
    const d = await _post('/german/calibrate', { answers });
    if (d.ok === false) throw new Error(d.error || 'failed');
    const lvl = d.recommended_level || d.level || d.recommended || '';
    res.innerHTML = lvl
      ? '<div class="german-ok">recommended level: <strong>' + _esc(lvl) + '</strong> ' +
        '<button type="button" class="german-cal-use setup-btn" data-lvl="' + _esc(lvl) + '">use this level</button></div>'
      : '<div class="sysdiag-muted">' + _esc(JSON.stringify(d).slice(0, 200)) + '</div>';
    const useBtn = res.querySelector('.german-cal-use');
    if (useBtn) useBtn.addEventListener('click', () => {
      const sel = _root.querySelector('.german-level-sel');
      if (sel) { sel.value = useBtn.getAttribute('data-lvl'); _setLevel(sel.value); }
      if (window.showToast) window.showToast('Level set to ' + useBtn.getAttribute('data-lvl'));
    });
  } catch (e) {
    res.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + '</div>';
  }
}

async function _loadCorrections() {
  const box = _root.querySelector('.german-hist');
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get('/german/corrections?limit=20');
    const recs = d.records || [];
    if (!recs.length) { box.innerHTML = '<div class="sysdiag-muted">no corrections yet — check some German above</div>'; return; }
    box.innerHTML = '<ul class="german-histlist">' + recs.map((r) => {
      const orig = _esc(r.original ?? r.text ?? r.input ?? '');
      const fixed = _esc(r.corrected ?? r.correction ?? r.fixed ?? '');
      const n = (r.errors != null) ? r.errors : (Array.isArray(r.issues) ? r.issues.length : null);
      return '<li><div class="german-hist-orig">' + orig + '</div>' +
        (fixed ? '<div class="german-hist-fixed">→ ' + fixed + '</div>' : '') +
        (n != null ? '<div class="german-hist-meta">' + n + ' issue' + (n === 1 ? '' : 's') +
          (r.level ? ' · ' + _esc(r.level) : '') + '</div>' : '') + '</li>';
    }).join('') + '</ul>';
  } catch (e) {
    box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + '</div>';
  }
}

async function _check() {
  const ta = _root.querySelector('.german-input');
  const out = _root.querySelector('.german-result');
  const text = (ta.value || '').trim();
  if (!text) { out.innerHTML = '<div class="sysdiag-muted">type something first</div>'; return; }
  out.innerHTML = '<div class="sysdiag-muted">checking…</div>';
  try {
    const d = await _post('/german/correct', { text });
    if (d.ok === false) throw new Error(d.error || 'failed');
    const errs = d.errors || [];
    if (!errs.length) {
      out.innerHTML = '<div class="german-ok">✓ looks good — no issues found' + (d.level ? ' · level ' + _esc(d.level) : '') + '</div>';
      return;
    }
    out.innerHTML =
      '<div class="german-errcount">' + errs.length + ' issue' + (errs.length === 1 ? '' : 's') + ' · level ' + _esc(d.level ?? '') + '</div>' +
      '<ul class="german-errs">' + errs.map((e) =>
        '<li><span class="german-err-match">' + _esc(e.match ?? e.text ?? '') + '</span> → <span class="german-err-hint">' + _esc(e.hint ?? e.suggestion ?? '') + '</span></li>'
      ).join('') + '</ul>';
  } catch (e) {
    out.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + '</div>';
  }
}

async function _refreshStats() {
  try {
    const s = await _get('/german/flashcards/stats');
    const el = _root.querySelector('.german-fc-stats');
    if (el) el.textContent = s.ok !== false ? '(' + (s.due ?? 0) + ' due · ' + (s.total ?? 0) + ' total)' : '';
  } catch (_) {}
}

async function _startReview() {
  const box = _root.querySelector('.german-fc');
  box.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get('/german/flashcards/due');
    _fc.queue = d.cards || [];
    _fc.idx = 0; _fc.revealed = false; _fc.reviewed = 0;
    if (!_fc.queue.length) { box.innerHTML = '<div class="german-ok">✓ nothing due — you’re caught up</div>'; return; }
    _renderCard();
  } catch (e) {
    box.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + '</div>';
  }
}

function _renderCard() {
  const box = _root.querySelector('.german-fc');
  const card = _fc.queue[_fc.idx];
  if (!card) { box.innerHTML = '<div class="german-ok">✓ done — ' + _fc.reviewed + ' reviewed</div>'; _refreshStats(); return; }
  if (!_fc.revealed) {
    box.innerHTML =
      '<div class="german-card"><div class="german-card-front">' + _esc(card.front) + '</div>' +
      '<button type="button" class="german-reveal setup-btn">reveal</button>' +
      '<div class="german-card-count">' + (_fc.idx + 1) + ' / ' + _fc.queue.length + '</div></div>';
    box.querySelector('.german-reveal').addEventListener('click', () => { _fc.revealed = true; _renderCard(); });
  } else {
    box.innerHTML =
      '<div class="german-card"><div class="german-card-front">' + _esc(card.front) + '</div>' +
      '<div class="german-card-back">' + _esc(card.back) + (card.example ? '<div class="german-card-eg">' + _esc(card.example) + '</div>' : '') + '</div>' +
      '<div class="german-rate">' +
        '<button type="button" data-q="1">again</button><button type="button" data-q="3">hard</button>' +
        '<button type="button" data-q="4">good</button><button type="button" data-q="5">easy</button>' +
      '</div><div class="german-card-count">' + (_fc.idx + 1) + ' / ' + _fc.queue.length + '</div></div>';
    box.querySelectorAll('.german-rate button').forEach((b) =>
      b.addEventListener('click', () => _rate(card.id, parseInt(b.getAttribute('data-q'), 10))));
  }
}

async function _rate(cardId, quality) {
  try { await _post('/german/flashcards/' + cardId + '/review', { quality }); } catch (_) {}
  _fc.reviewed += 1; _fc.idx += 1; _fc.revealed = false;
  _renderCard();
}

async function _setLevel(level) {
  try { await _post('/german/profile/level', { level }); if (window.showToast) window.showToast('German level → ' + level); } catch (_) {}
}

export async function openGerman() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _root.querySelector('.german-fc').innerHTML = '';
  _root.querySelector('.german-result').innerHTML = '';
  try {
    const p = await _get('/german/profile');
    const lvl = p && p.profile && p.profile.level;
    if (lvl && _LEVELS.includes(lvl)) _root.querySelector('.german-level-sel').value = lvl;
  } catch (_) {}
  _refreshStats();
}

export function closeGerman() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

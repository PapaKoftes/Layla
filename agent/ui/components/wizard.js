/**
 * components/wizard.js — First-run wizard (6-step onboarding flow).
 *
 * Converted from js/layla-wizard.js (IIFE -> ES module).
 * Depends on: services/utils.js (escapeHtml), components/aspect.js (setAspect, ASPECTS)
 */

import { escapeHtml } from '../services/utils.js';
import { ASPECTS } from './aspect.js';

// ── Constants ───────────────────────────────────────────────────────────────
const WIZ_KEY = 'layla_wizard_v2_done';
const WIZ_KEY_COMPAT = 'layla_wizard_done';

// ── First-run ownership (BL-249/BL-250) ─────────────────────────────────────
// The 6-step wizard is the introduction. It runs on window `load`, but the welcome/profile cascade
// (setup.js maybeStartSetupProfiles, reached from app.js init at DOMContentLoaded) and the onboarding
// interview (onboarding.js, 2s after load) race it and could stack a second "Meet Layla" modal on top.
// A single shared string on window — set SYNCHRONOUSLY in initWizard() before app.js init runs — lets
// those later surfaces yield until the wizard has decided and finished. No module import (that is what
// killed the previous attempt); the value is the coordination.
//   'deciding' — the wizard has not yet consulted the server; it MIGHT show. Later surfaces wait.
//   'showing'  — the wizard is on screen. Later surfaces wait.
//   'released' — the wizard is done (completed, or it decided not to show). Later surfaces may proceed.
function _setClaim(state) {
  try { window._laylaFirstRunClaim = state; } catch (_) {}
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }
function _esc(s) { return escapeHtml(String(s)); }

// ── State ───────────────────────────────────────────────────────────────────
let step = 0;
let quizStage = 0;
const quizAnswers = [];
let chosenAspect = 'morrigan';

// ── Visibility ──────────────────────────────────────────────────────────────
function wizardVisible() {
  const ov = $('wizard-overlay');
  return !!(ov && ov.classList.contains('visible'));
}

function setVisible(on) {
  const ov = $('wizard-overlay');
  if (!ov) return;
  ov.classList.toggle('visible', !!on);
  ov.setAttribute('aria-hidden', on ? 'false' : 'true');
}

// ── Step navigation ─────────────────────────────────────────────────────────
function applyStep() {
  const ov = $('wizard-overlay');
  if (!ov) return;
  ov.querySelectorAll('.wizard-step').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-wstep') === String(step));
  });
  ov.querySelectorAll('.wizard-dot').forEach(d => {
    d.classList.toggle('active', d.getAttribute('data-step') === String(step));
  });
  const back = $('wizard-back-btn');
  const next = $('wizard-next-btn');
  if (back) back.style.visibility = (step === 0) ? 'hidden' : 'visible';
  if (next) next.textContent = (step === 5) ? 'Enter' : 'Next';

  if (step === 1) {
    try {
      if (typeof window.checkSetupStatus === 'function') {
        window.checkSetupStatus().catch(() => {});
      }
    } catch (_) {}
  }
  if (step === 3) {
    renderQuizStage().catch(() => {});
  }
  if (step === 4) {
    renderAspects();
  }
}

// ── Quiz ────────────────────────────────────────────────────────────────────
async function renderQuizStage() {
  const promptEl = $('wizard-quiz-prompt');
  const optionsEl = $('wizard-quiz-options');
  const progEl = $('wizard-quiz-progress');
  if (!promptEl || !optionsEl || !progEl) return;
  promptEl.textContent = 'Loading…';
  optionsEl.innerHTML = '';
  progEl.textContent = '';
  const r = await fetch('/operator/quiz/stage/' + String(quizStage));
  const d = await r.json().catch(() => ({}));
  if (!d || d.ok === false) {
    promptEl.textContent = 'Could not load quiz.';
    optionsEl.innerHTML = '<button type="button" class="tab-btn" onclick="location.reload()">Reload</button>';
    return;
  }
  const qs = (d.questions && d.questions[0]) ? d.questions[0] : null;
  if (!qs) { promptEl.textContent = 'Quiz complete.'; return; }
  promptEl.textContent = String(qs.prompt || '');
  progEl.textContent = 'Question ' + String(quizStage + 1) + ' of 9';
  const opts = Array.isArray(qs.options) ? qs.options : [];
  optionsEl.innerHTML = opts.map(o => {
    return '<button type="button" class="tab-btn" style="text-align:left;white-space:normal;line-height:1.35;padding:10px 10px" data-qid="' + _esc(qs.id) + '" data-oid="' + _esc(o.id) + '">' + _esc(o.label) + '</button>';
  }).join('');
  optionsEl.querySelectorAll('button[data-qid]').forEach(b => {
    b.addEventListener('click', async () => {
      const qid = String(b.getAttribute('data-qid') || '');
      const oid = String(b.getAttribute('data-oid') || '');
      quizAnswers[quizStage] = { question_id: qid, option_id: oid };
      if (quizStage < 8) {
        quizStage += 1;
        await renderQuizStage();
        return;
      }
      // finalize
      promptEl.textContent = 'Saving…';
      optionsEl.innerHTML = '';
      progEl.textContent = '';
      try {
        await fetch('/operator/quiz/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: quizAnswers.filter(Boolean), finalize: true }),
        });
      } catch (_) {}
      step = 4;
      applyStep();
      try {
        if (typeof window.refreshMaturityCard === 'function') window.refreshMaturityCard(false);
      } catch (_) {}
    });
  });
}

// ── Aspect chooser ──────────────────────────────────────────────────────────
function renderAspects() {
  const wrap = $('wizard-aspects');
  if (!wrap) return;
  wrap.innerHTML = ASPECTS.map(a => {
    const active = (a.id === chosenAspect);
    return '<button type="button" class="tab-btn" data-asp="' + _esc(a.id) + '" style="padding:10px;border-color:' + (active ? 'var(--asp)' : 'var(--border)') + ';text-align:left">' +
      '<div style="font-size:0.92rem"><strong>' + _esc(a.sym + ' ' + a.name) + '</strong></div>' +
      '<div style="font-size:0.72rem;color:var(--text-dim);margin-top:4px;line-height:1.35">' + _esc(a.desc) + '</div>' +
      '</button>';
  }).join('');
  wrap.querySelectorAll('button[data-asp]').forEach(b => {
    b.addEventListener('click', () => {
      chosenAspect = String(b.getAttribute('data-asp') || 'morrigan');
      try {
        if (typeof window.setAspect === 'function') window.setAspect(chosenAspect);
      } catch (_) {}
      try { localStorage.setItem('layla_default_aspect', chosenAspect); } catch (_) {}
      renderAspects();
    });
  });
}

// ── Navigation ──────────────────────────────────────────────────────────────
function syncWorkspaceToSettings() {
  const wizPath = $('wizard-workspace-path');
  const v = String(wizPath?.value || '').trim();
  if (!v) return;
  try { const el = $('workspace-path'); if (el) el.value = v; } catch (_) {}
  try { const el = $('setup-workspace-path'); if (el) el.value = v; } catch (_) {}
}

async function onNext() {
  if (step === 1) {
    try {
      if (typeof window.checkSetupStatus === 'function') await window.checkSetupStatus();
    } catch (_) {}
  }
  if (step === 2) syncWorkspaceToSettings();
  if (step === 3) return; // quiz advances itself
  if (step === 5) {
    try { localStorage.setItem(WIZ_KEY, '1'); } catch (_) {}
    try { localStorage.setItem(WIZ_KEY_COMPAT, '1'); } catch (_) {}
    // SERVER-side truth is what makes "introduced once" stick across a cleared localStorage or a second
    // browser — it is the whole reason the `ready` shortcut could be removed safely (BL-250). If this POST
    // is silently dropped the wizard would return on every new browser, so test_wizard_first_run_gate.py
    // asserts the round-trip against a live server rather than trusting it.
    try {
      await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wizard_complete: true }),
      });
    } catch (_) {}
    setVisible(false);
    _setClaim('released');  // our turn is over — later surfaces may run
    // Hand off to the tour (BL-249): the wizard introduces the app; the tour explains the things that are
    // not self-evident — workspace scoping, aspect selection, the lock, and Ctrl+K. This is what actually
    // starts the tour; the welcome/profile cascade stays yielded (it never ran while the wizard owned
    // first-run), so there is no double-introduction.
    try {
      if (typeof window.maybeStartTour === 'function') window.maybeStartTour();
    } catch (_) {}
    return;
  }
  step += 1;
  applyStep();
}

function onBack() {
  if (step <= 0) return;
  if (step === 3 && quizStage > 0) {
    quizStage = Math.max(0, quizStage - 1);
    renderQuizStage().catch(() => {});
    return;
  }
  step -= 1;
  applyStep();
}

// ── Binding ─────────────────────────────────────────────────────────────────
function bind() {
  const ov = $('wizard-overlay');
  if (!ov) return;
  ov.addEventListener('click', e => {
    // no backdrop-dismiss
    e.preventDefault();
    e.stopPropagation();
  });
  $('wizard-next-btn')?.addEventListener('click', () => { onNext().catch(() => {}); });
  $('wizard-back-btn')?.addEventListener('click', onBack);
  document.addEventListener('keydown', e => {
    if (!wizardVisible()) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      const ae = document.activeElement;
      const inText = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA');
      if (inText && step !== 0 && step !== 5) return;
      e.preventDefault();
      e.stopPropagation();
      onNext().catch(() => {});
    }
  }, true);
}

// ── Start wizard ────────────────────────────────────────────────────────────
export async function laylaWizardStart() {
  try {
    if (localStorage.getItem(WIZ_KEY) === '1' || localStorage.getItem(WIZ_KEY_COMPAT) === '1') {
      _setClaim('released');  // introduced already in this browser — later surfaces may proceed
      return;
    }
  } catch (_) {}
  // Consult SERVER truth before nagging: localStorage is per-browser + fragile, so a returning user on a
  // second browser would otherwise be re-introduced forever.
  //
  // BL-250 — `ready` and `wizard_complete` are two DIFFERENT propositions and this gate used to conflate
  // them:
  //   ready           = "a valid GGUF is provisioned"      (routers/settings.py: "ready": model_found)
  //   wizard_complete = "a human was actually introduced"  (set below, only after they finish the wizard)
  // An installer or CLI that provisions a model sets ready=true without ever showing this wizard — so the
  // BETTER the install went, the LESS the friend was told: she lost the workspace picker, the character
  // quiz, the aspect picker and the feature list precisely BECAUSE setup succeeded. Worse, the old code
  // then wrote the "wizard done" marker for someone who had never seen it, making the skip permanent and
  // self-concealing. So: only a human finishing the wizard may skip it. A provisioned model no longer
  // implies an introduced user. This does NOT re-open the "wizard on every launch" bug the `ready` clause
  // was papering over — that is fixed properly by persisting wizard_complete SERVER-side on completion
  // (onNext, step 5), which survives a cleared localStorage and a browser switch.
  try {
    const _f = window.fetchWithTimeout
      ? window.fetchWithTimeout('/setup_status', {}, 8000)
      : fetch('/setup_status');
    const res = await _f;
    if (res && res.ok) {
      const s = await res.json();
      if (s && s.wizard_complete === true) {
        // A human finished it. Cache locally so we stop asking the server every launch.
        try {
          localStorage.setItem(WIZ_KEY, '1');
          localStorage.setItem(WIZ_KEY_COMPAT, '1');
        } catch (_) {}
        _setClaim('released');
        return;
      }
    }
  } catch (_) { /* server unreachable — fall through to first-run wizard */ }
  bind();
  _setClaim('showing');  // set BEFORE paint: the claim is what holds back later surfaces, not the class
  setVisible(true);
  step = 0;
  applyStep();
  const nextBtn = $('wizard-next-btn');
  if (nextBtn) nextBtn.disabled = true;
  // Pre-fill workspace if present in Settings
  try {
    const existing = String($('workspace-path')?.value || '').trim();
    if (existing && $('wizard-workspace-path')) $('wizard-workspace-path').value = existing;
    if (existing && $('setup-workspace-path')) $('setup-workspace-path').value = existing;
  } catch (_) {}
  try {
    if (typeof window.checkSetupStatus === 'function') await window.checkSetupStatus();
  } catch (_) {}
  if (nextBtn) nextBtn.disabled = false;
}

// ── Init — called from main.js ──────────────────────────────────────────────
export function initWizard() {
  // Set the first-run claim SYNCHRONOUSLY, here in init, so it is already in place before app.js's init
  // (same pass) fires checkSetupStatus() → the welcome/profile cascade. localStorage is synchronous, so we
  // can decide the cheap half now: if this browser already finished the wizard, later surfaces are free
  // immediately; otherwise the wizard might still show, so hold them at 'deciding' until laylaWizardStart
  // resolves the server check on window `load`.
  try {
    const done = localStorage.getItem(WIZ_KEY) === '1' || localStorage.getItem(WIZ_KEY_COMPAT) === '1';
    _setClaim(done ? 'released' : 'deciding');
  } catch (_) { _setClaim('deciding'); }
  // Boot after load so layla-app.js globals exist
  window.addEventListener('load', () => { laylaWizardStart().catch(() => {}); });
}

(function () {
  'use strict';

  const WIZ_KEY = 'layla_wizard_v2_done';
  const WIZ_KEY_COMPAT = 'layla_wizard_done';

  function $(id) { return document.getElementById(id); }
  function _esc(s) {
    try { return (typeof window.escapeHtml === 'function') ? window.escapeHtml(String(s)) : String(s); }
    catch (_) { return String(s); }
  }

  let step = 0;
  let quizStage = 0;
  const quizAnswers = [];
  let chosenAspect = 'morrigan';

  const ASPECTS = [
    { id: 'morrigan', sym: '⚔', name: 'Morrigan', desc: 'Code, debug, architecture.' },
    { id: 'nyx', sym: '✦', name: 'Nyx', desc: 'Research, depth, synthesis.' },
    { id: 'echo', sym: '◎', name: 'Echo', desc: 'Reflection, patterns, memory.' },
    { id: 'eris', sym: '⚡', name: 'Eris', desc: 'Creative chaos, ideation.' },
    { id: 'cassandra', sym: '⌖', name: 'Cassandra', desc: 'Rapid critique, blunt truth.' },
    { id: 'lilith', sym: '⊛', name: 'Lilith', desc: 'Ethics, boundaries, sovereignty.' },
  ];

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

  function applyStep() {
    const ov = $('wizard-overlay');
    if (!ov) return;
    ov.querySelectorAll('.wizard-step').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-wstep') === String(step));
    });
    ov.querySelectorAll('.wizard-dot').forEach(function (d) {
      d.classList.toggle('active', d.getAttribute('data-step') === String(step));
    });
    const back = $('wizard-back-btn');
    const next = $('wizard-next-btn');
    if (back) back.style.visibility = (step === 0) ? 'hidden' : 'visible';
    if (next) next.textContent = (step === 5) ? 'Enter' : 'Next';

    if (step === 3) {
      renderQuizStage().catch(function () {});
    }
    if (step === 4) {
      renderAspects();
    }
  }

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
    optionsEl.innerHTML = opts.map(function (o) {
      return '<button type="button" class="tab-btn" style="text-align:left;white-space:normal;line-height:1.35;padding:10px 10px" data-qid="' + _esc(qs.id) + '" data-oid="' + _esc(o.id) + '">' + _esc(o.label) + '</button>';
    }).join('');
    optionsEl.querySelectorAll('button[data-qid]').forEach(function (b) {
      b.addEventListener('click', async function () {
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
        try { if (typeof window.refreshMaturityCard === 'function') window.refreshMaturityCard(false); } catch (_) {}
      });
    });
  }

  function renderAspects() {
    const wrap = $('wizard-aspects');
    if (!wrap) return;
    wrap.innerHTML = ASPECTS.map(function (a) {
      const active = (a.id === chosenAspect);
      return '<button type="button" class="tab-btn" data-asp="' + _esc(a.id) + '" style="padding:10px;border-color:' + (active ? 'var(--asp)' : 'var(--border)') + ';text-align:left">' +
        '<div style="font-size:0.92rem"><strong>' + _esc(a.sym + ' ' + a.name) + '</strong></div>' +
        '<div style="font-size:0.72rem;color:var(--text-dim);margin-top:4px;line-height:1.35">' + _esc(a.desc) + '</div>' +
        '</button>';
    }).join('');
    wrap.querySelectorAll('button[data-asp]').forEach(function (b) {
      b.addEventListener('click', function () {
        chosenAspect = String(b.getAttribute('data-asp') || 'morrigan');
        try { if (typeof window.setAspect === 'function') window.setAspect(chosenAspect); } catch (_) {}
        try { localStorage.setItem('layla_default_aspect', chosenAspect); } catch (_) {}
        renderAspects();
      });
    });
  }

  function syncWorkspaceToSettings() {
    const v = String($('wizard-workspace-path')?.value || '').trim();
    if (!v) return;
    try { if ($('workspace-path')) $('workspace-path').value = v; } catch (_) {}
    try { if ($('setup-workspace-path')) $('setup-workspace-path').value = v; } catch (_) {}
  }

  async function onNext() {
    if (step === 1) {
      // attempt to refresh setup status in case model became ready
      try { if (typeof window.checkSetupStatus === 'function') await window.checkSetupStatus(); } catch (_) {}
    }
    if (step === 2) syncWorkspaceToSettings();
    if (step === 3) return; // quiz advances itself
    if (step === 5) {
      try { localStorage.setItem(WIZ_KEY, '1'); } catch (_) {}
      try { localStorage.setItem(WIZ_KEY_COMPAT, '1'); } catch (_) {}
      try {
        await fetch('/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ wizard_complete: true }),
        });
      } catch (_) {}
      setVisible(false);
      return;
    }
    step += 1;
    applyStep();
  }

  function onBack() {
    if (step <= 0) return;
    if (step === 3 && quizStage > 0) {
      quizStage = Math.max(0, quizStage - 1);
      renderQuizStage().catch(function () {});
      return;
    }
    step -= 1;
    applyStep();
  }

  function bind() {
    const ov = $('wizard-overlay');
    if (!ov) return;
    ov.addEventListener('click', function (e) {
      // no backdrop-dismiss; ignore clicks
      e.preventDefault();
      e.stopPropagation();
    });
    $('wizard-next-btn')?.addEventListener('click', function () { onNext().catch(function () {}); });
    $('wizard-back-btn')?.addEventListener('click', onBack);
    document.addEventListener('keydown', function (e) {
      if (!wizardVisible()) return;
      if (e.key === 'Escape') {
        // Block escape until final step.
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        // Avoid stealing Enter inside inputs (workspace path, url) except in welcome/ready.
        const ae = document.activeElement;
        const inText = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA');
        if (inText && step !== 0 && step !== 5) return;
        e.preventDefault();
        e.stopPropagation();
        onNext().catch(function () {});
      }
    }, true);
  }

  async function start() {
    try {
      if (localStorage.getItem(WIZ_KEY) === '1' || localStorage.getItem(WIZ_KEY_COMPAT) === '1') return;
    } catch (_) {}
    bind();
    setVisible(true);
    step = 0;
    applyStep();
    // Pre-fill workspace if present in Settings
    try {
      const existing = String($('workspace-path')?.value || '').trim();
      if (existing && $('wizard-workspace-path')) $('wizard-workspace-path').value = existing;
      if (existing && $('setup-workspace-path')) $('setup-workspace-path').value = existing;
    } catch (_) {}
    try { if (typeof window.checkSetupStatus === 'function') await window.checkSetupStatus(); } catch (_) {}
  }

  window.laylaWizardStart = start;

  // Boot after load so layla-app.js globals exist.
  window.addEventListener('load', function () { start().catch(function () {}); });
})();


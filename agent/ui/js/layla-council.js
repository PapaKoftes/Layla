/* Layla Council — one-click multi-aspect deliberation.
 *
 * Takes the current composer text as a goal, runs POST /debate (mode=council),
 * and renders each aspect's take, their critiques, the points of agreement /
 * disagreement, and the final synthesis as a single card in the chat.
 *
 * Self-contained: depends only on /debate, marked + DOMPurify (optional, for
 * markdown), and the --asp-* CSS color variables already defined in layla.css.
 */
(function () {
  'use strict';

  var ASPECT_META = {
    morrigan:  { sym: '⚔', name: 'Morrigan',  color: 'var(--asp-morrigan)' },
    nyx:       { sym: '✦', name: 'Nyx',       color: 'var(--asp-nyx)' },
    echo:      { sym: '◎', name: 'Echo',      color: 'var(--asp-echo)' },
    eris:      { sym: '⚡', name: 'Eris',      color: 'var(--asp-eris)' },
    cassandra: { sym: '⌖', name: 'Cassandra', color: 'var(--asp-cassandra)' },
    lilith:    { sym: '⊛', name: 'Lilith',    color: 'var(--asp-lilith)' },
  };

  var MODE_LABELS = {
    solo: 'Solo', debate: '⚔ Debate', council: '⊛ Council', tribunal: '✦ Tribunal',
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Safe markdown: prefer marked + DOMPurify (already loaded for chat), else
  // fall back to escaped text with line breaks. Never inject raw HTML.
  function md(text) {
    var t = text == null ? '' : String(text);
    try {
      if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(marked.parse(t));
      }
    } catch (_) {}
    return esc(t).replace(/\n/g, '<br>');
  }

  function metaFor(id) {
    var key = String(id || '').toLowerCase();
    return ASPECT_META[key] || { sym: '◆', name: (id || 'aspect'), color: 'var(--asp)' };
  }

  function toast(m) { if (typeof window.showToast === 'function') window.showToast(m); }

  function buildCard(goal, data) {
    var card = document.createElement('div');
    card.className = 'council-card';
    var modeLabel = MODE_LABELS[data.mode] || data.mode || 'Council';
    var parts = Array.isArray(data.participating_aspects) ? data.participating_aspects : [];
    var html = '';

    html += '<div class="council-head">';
    html += '<span class="council-mode">' + esc(modeLabel) + '</span>';
    html += '<span class="council-goal">' + esc(goal) + '</span>';
    html += '</div>';

    if (parts.length) {
      html += '<div class="council-chips">';
      parts.forEach(function (id) {
        var m = metaFor(id);
        html += '<span class="council-chip" style="border-color:' + m.color + ';color:' + m.color + '">'
             + esc(m.sym) + ' ' + esc(m.name) + '</span>';
      });
      html += '</div>';
    }

    var responses = data.aspect_responses || {};
    var critiques = data.critiques || {};
    var ids = Object.keys(responses);
    if (ids.length) {
      html += '<div class="council-aspects">';
      ids.forEach(function (id) {
        var m = metaFor(id);
        html += '<details class="council-aspect" open>';
        html += '<summary style="border-left:3px solid ' + m.color + '">'
             + '<span style="color:' + m.color + '">' + esc(m.sym) + ' ' + esc(m.name) + '</span></summary>';
        html += '<div class="council-aspect-body md-content">' + md(responses[id]) + '</div>';
        var crit = critiques[id];
        if (crit && String(crit).trim()) {
          html += '<div class="council-critique"><span class="council-critique-label">Critique</span>'
               + '<div class="md-content">' + md(crit) + '</div></div>';
        }
        html += '</details>';
      });
      html += '</div>';
    }

    if (data.synthesis_notes && String(data.synthesis_notes).trim() && data.synthesis_notes !== 'synthesis_failed') {
      html += '<div class="council-notes"><span class="council-notes-label">Where they agree &amp; differ</span>'
           + '<div class="md-content">' + md(data.synthesis_notes) + '</div></div>';
    }

    html += '<div class="council-final">';
    html += '<div class="council-final-label">⊛ Synthesis</div>';
    html += '<div class="council-final-body md-content">' + md(data.final_response || '(no synthesis produced)') + '</div>';
    html += '</div>';

    card.innerHTML = html;
    return card;
  }

  function appendToChat(node) {
    var chat = document.getElementById('chat');
    if (!chat) return null;
    var wrap = document.createElement('div');
    wrap.className = 'msg msg-layla council-msg';
    wrap.appendChild(node);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  async function runCouncil(modeArg) {
    var input = document.getElementById('msg-input');
    var goal = input ? (input.value || '').trim() : '';
    if (!goal) {
      toast('Type a question first — the Council deliberates on your prompt');
      if (input) input.focus();
      return;
    }
    var mode = modeArg || 'council';

    var chat = document.getElementById('chat');
    if (chat) {
      var you = document.createElement('div');
      you.className = 'msg msg-you';
      you.innerHTML = '<div class="msg-label">You → Council</div><div class="msg-bubble">' + esc(goal) + '</div>';
      chat.appendChild(you);
    }
    if (input) { input.value = ''; if (typeof window.onInputChange === 'function') { try { window.onInputChange(); } catch (_) {} } }

    var loading = document.createElement('div');
    loading.className = 'council-card council-loading';
    loading.innerHTML = '<div class="council-head"><span class="council-mode">' + esc(MODE_LABELS[mode] || 'Council')
      + '</span><span class="council-goal">' + esc(goal) + '</span></div>'
      + '<div class="council-spinner">Aspects are deliberating… (this runs several model passes, give it a moment)</div>';
    var wrap = appendToChat(loading);

    var btn = document.getElementById('council-btn');
    if (btn) { btn.disabled = true; btn.classList.add('busy'); }
    try {
      var r = await fetch('/debate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: goal, mode: mode }),
      });
      var data = await r.json().catch(function () { return {}; });
      if (!data || data.ok === false) {
        var sp = loading.querySelector('.council-spinner');
        if (sp) sp.textContent = 'Council failed: ' + ((data && data.error) || ('HTTP ' + r.status));
        loading.classList.add('council-error');
        return;
      }
      var card = buildCard(goal, data);
      if (wrap) { wrap.innerHTML = ''; wrap.appendChild(card); }
      if (chat) chat.scrollTop = chat.scrollHeight;
    } catch (e) {
      var sp2 = loading.querySelector('.council-spinner');
      if (sp2) sp2.textContent = 'Council error: ' + ((e && e.message) || e);
      loading.classList.add('council-error');
    } finally {
      if (btn) { btn.disabled = false; btn.classList.remove('busy'); }
    }
  }

  window.runCouncil = runCouncil;
})();

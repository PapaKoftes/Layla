/**
 * Chat lifecycle phases for Layla UI — data-layla-phase on bubbles + body hint for global FX.
 * Loaded before layla-app.js (classic script, no modules — matches rest of UI).
 */
(function () {
  'use strict';

  function mapUxKeyToPhase(uxKey) {
    if (!uxKey) return 'idle';
    const k = String(uxKey);
    if (k === 'connecting') return 'connecting';
    if (k === 'waiting_first_token') return 'thinking';
    if (k === 'streaming') return 'streaming';
    if (k === 'tool_running' || k === 'verifying') return 'tool';
    if (k === 'preparing_reply') return 'typing';
    if (k === 'stalled') return 'stalled';
    if (
      k === 'thinking' ||
      k === 'still_working' ||
      k === 'changing_approach' ||
      k === 'reframing_objective'
    )
      return 'thinking';
    if (k === 'approaching_context_limit' || k === 'context_critical') return 'thinking';
    return 'thinking';
  }

  function applyPhaseToBubble(bubble, uxKey) {
    if (!bubble || !bubble.classList) return;
    const phase = mapUxKeyToPhase(uxKey);
    bubble.setAttribute('data-layla-phase', phase);
  }

  function syncBodyPhase(uxKey) {
    if (!document.body) return;
    const phase = mapUxKeyToPhase(uxKey);
    document.body.setAttribute('data-layla-chat-phase', phase);
  }

  function clearBodyPhase() {
    document.body?.removeAttribute('data-layla-chat-phase');
  }

  /** @param {HTMLElement|null} typingWrap - #typing-wrap */
  function applyToTypingWrap(typingWrap, uxKey) {
    if (!typingWrap) return;
    const bubble = typingWrap.querySelector('.msg-bubble');
    applyPhaseToBubble(bubble, uxKey);
    syncBodyPhase(uxKey);
  }

  /**
   * @param {HTMLElement|null} row - .msg.msg-layla stream or typing row
   * @param {string} uxKey
   */
  function syncStreamRowPhase(row, uxKey) {
    if (!row) return;
    const bubble = row.querySelector('.msg-bubble');
    applyPhaseToBubble(bubble, uxKey);
    syncBodyPhase(uxKey);
  }

  window.LaylaUI = window.LaylaUI || {};
  window.LaylaUI.mapUxKeyToPhase = mapUxKeyToPhase;
  window.LaylaUI.applyPhaseToBubble = applyPhaseToBubble;
  window.LaylaUI.syncBodyPhase = syncBodyPhase;
  window.LaylaUI.clearBodyPhase = clearBodyPhase;
  window.LaylaUI.applyToTypingWrap = applyToTypingWrap;
  window.LaylaUI.syncStreamRowPhase = syncStreamRowPhase;
})();

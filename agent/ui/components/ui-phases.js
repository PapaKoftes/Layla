/**
 * components/ui-phases.js — Chat lifecycle phase mapping.
 *
 * Maps UX state keys to visual phases (data-layla-phase on bubbles,
 * data-layla-chat-phase on body for global FX).
 *
 * Converted from js/layla-ui-phases.js (IIFE → ES module).
 */

export function mapUxKeyToPhase(uxKey) {
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
  ) return 'thinking';
  if (k === 'approaching_context_limit' || k === 'context_critical') return 'thinking';
  return 'thinking';
}

export function applyPhaseToBubble(bubble, uxKey) {
  if (!bubble || !bubble.classList) return;
  bubble.setAttribute('data-layla-phase', mapUxKeyToPhase(uxKey));
}

export function syncBodyPhase(uxKey) {
  if (!document.body) return;
  document.body.setAttribute('data-layla-chat-phase', mapUxKeyToPhase(uxKey));
}

export function clearBodyPhase() {
  document.body?.removeAttribute('data-layla-chat-phase');
}

export function applyToTypingWrap(typingWrap, uxKey) {
  if (!typingWrap) return;
  const bubble = typingWrap.querySelector('.msg-bubble');
  applyPhaseToBubble(bubble, uxKey);
  syncBodyPhase(uxKey);
}

export function syncStreamRowPhase(row, uxKey) {
  if (!row) return;
  const bubble = row.querySelector('.msg-bubble');
  applyPhaseToBubble(bubble, uxKey);
  syncBodyPhase(uxKey);
}

export const LaylaUI = {
  mapUxKeyToPhase,
  applyPhaseToBubble,
  syncBodyPhase,
  clearBodyPhase,
  applyToTypingWrap,
  syncStreamRowPhase,
};

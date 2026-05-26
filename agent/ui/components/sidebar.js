/**
 * components/sidebar.js — Sidebar helpers.
 *
 * Converted from js/sidebar.js (IIFE → ES module).
 */

import { appState } from '../core/state.js';

export function scrollActiveConversationIntoView() {
  try {
    const id = appState.get('chat.conversationId') || '';
    if (!id) return;
    const el = document.querySelector(`.chat-rail-item.active[data-conv-id="${id.replace(/"/g, '')}"]`)
      || document.querySelector(`[data-conversation-id="${id.replace(/"/g, '')}"]`);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  } catch (_) {}
}

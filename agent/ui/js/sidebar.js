/**
 * Sidebar helpers: scroll active conversation into view when rail updates.
 */
(function () {
  'use strict';
  window.laylaScrollActiveConversationIntoView = function () {
    try {
      var id = (typeof currentConversationId !== 'undefined' && currentConversationId) ? String(currentConversationId) : '';
      if (!id) return;
      var el = document.querySelector('.chat-rail-item.active[data-conv-id="' + id.replace(/"/g, '') + '"]')
        || document.querySelector('[data-conversation-id="' + id.replace(/"/g, '') + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
    } catch (_) {}
  };
})();

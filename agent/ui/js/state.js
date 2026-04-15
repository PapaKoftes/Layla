/**
 * Chat UI finite state machine — guards concurrent sends / stream.
 */
(function () {
  'use strict';
  var ChatState = {
    IDLE: 'idle',
    SENDING: 'sending',
    STREAMING: 'streaming',
    DONE: 'done',
    ERROR: 'error',
  };

  var _st = ChatState.IDLE;

  function canSend() {
    return _st === ChatState.IDLE || _st === ChatState.DONE || _st === ChatState.ERROR;
  }

  function transition(next) {
    var n = String(next || '');
    _st = n;
    try {
      document.body && document.body.setAttribute('data-chat-fsm', n);
    } catch (_) {}
    try {
      if (typeof window.laylaOnChatState === 'function') window.laylaOnChatState(n);
    } catch (_) {}
  }

  window.LaylaChatState = ChatState;
  window.laylaChatFSM = {
    getState: function () { return _st; },
    canSend: canSend,
    transition: transition,
    beginSend: function () {
      if (!canSend()) return false;
      transition(ChatState.SENDING);
      return true;
    },
    beginStream: function () {
      transition(ChatState.STREAMING);
    },
    finishOk: function () {
      transition(ChatState.DONE);
      transition(ChatState.IDLE);
    },
    finishError: function () {
      transition(ChatState.ERROR);
      transition(ChatState.IDLE);
    },
  };
})();

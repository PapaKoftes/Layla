/**
 * core/state.js — Centralized application state for Layla UI.
 *
 * Replaces ~50 scattered window.* globals with a single observable store.
 * Modules read/write state through this API; the bus emits "state:changed"
 * events so any subscriber reacts to changes without polling or coupling.
 *
 * Usage:
 *   import { appState } from './core/state.js';
 *   appState.set('chat.conversationId', 'abc-123');
 *   const id = appState.get('chat.conversationId');
 *   appState.on('chat.conversationId', (newVal, oldVal) => { ... });
 *
 * Sections:
 *   chat.*       — FSM state, conversationId, streaming
 *   aspect.*     — current aspect, available aspects
 *   health.*     — server status, model, governor mode
 *   session.*    — start time, tokens, tool calls
 *   overlay.*    — active overlay stack
 *   settings.*   — user preferences
 *   cluster.*    — peer info, role
 *   growth.*     — XP, rank, phase
 */

import { bus } from './bus.js';

// ── Chat FSM states ──────────────────────────────────────────────────────────
export const ChatState = Object.freeze({
  IDLE:      'idle',
  SENDING:   'sending',
  STREAMING: 'streaming',
  DONE:      'done',
  ERROR:     'error',
});

// ── Internal state tree ──────────────────────────────────────────────────────
const _state = {
  chat: {
    fsm:              ChatState.IDLE,
    conversationId:   '',
    lastMessage:      null,
    streamingAbort:   null,      // AbortController for active stream
  },
  aspect: {
    current:    'morrigan',
    available:  ['morrigan', 'nyx', 'echo', 'eris', 'cassandra', 'lilith'],
  },
  health: {
    status:       'unknown',    // 'online' | 'degraded' | 'offline'
    modelLoaded:  false,
    modelName:    '',
    remoteMode:   false,
    governorMode: '',
    uptime:       0,
    lastCheck:    0,
    payload:      null,         // raw health response
  },
  session: {
    startTime:  Date.now(),
    tokens:     0,
    toolCalls:  0,
    elapsed:    0,
  },
  overlay: {
    stack:  [],                 // ordered list of open overlay IDs
  },
  settings: {
    workspace:      '',
    allowWrite:     false,
    allowRun:       false,
    showThinking:   false,
  },
  cluster: {
    enabled:    false,
    role:       'queen',
    peers:      0,
  },
  growth: {
    xp:     0,
    rank:   0,
    phase:  '',
  },
};

// ── Per-path watchers ────────────────────────────────────────────────────────
const _watchers = new Map();

/**
 * Deep-get a nested value by dot-path. Returns undefined if missing.
 */
function _deepGet(obj, path) {
  const keys = path.split('.');
  let cur = obj;
  for (let i = 0; i < keys.length; i++) {
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = cur[keys[i]];
  }
  return cur;
}

/**
 * Deep-set a nested value by dot-path. Creates intermediate objects.
 */
function _deepSet(obj, path, value) {
  const keys = path.split('.');
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (cur[keys[i]] == null || typeof cur[keys[i]] !== 'object') {
      cur[keys[i]] = {};
    }
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
}

/**
 * Get a state value by dot-path.
 * @param {string} path  e.g. "chat.conversationId"
 * @returns {*}
 */
function get(path) {
  return _deepGet(_state, path);
}

/**
 * Set a state value by dot-path.
 * Emits "state:changed" on bus and notifies per-path watchers.
 * @param {string} path
 * @param {*} value
 */
function set(path, value) {
  const old = _deepGet(_state, path);
  if (old === value) return; // no-op for identical primitives
  _deepSet(_state, path, value);

  // Emit global state change
  bus.emit('state:changed', { path, value, old });

  // Notify path-specific watchers
  const fns = _watchers.get(path);
  if (fns && fns.length > 0) {
    const snapshot = fns.slice();
    for (let i = 0; i < snapshot.length; i++) {
      try { snapshot[i](value, old); } catch (e) {
        console.error(`[state] watcher error on "${path}":`, e);
      }
    }
  }

  // Sync to DOM attribute for CSS hooks
  if (path === 'chat.fsm') {
    try { document.body.setAttribute('data-chat-fsm', value); } catch (_) {}
  }
  if (path === 'aspect.current') {
    try { document.body.setAttribute('data-aspect', value); } catch (_) {}
  }
}

/**
 * Watch a specific path for changes.
 * @param {string} path
 * @param {Function} fn  called with (newValue, oldValue)
 * @returns {Function} unsubscribe
 */
function watch(path, fn) {
  if (!_watchers.has(path)) _watchers.set(path, []);
  _watchers.get(path).push(fn);
  return function unwatch() {
    const arr = _watchers.get(path);
    if (!arr) return;
    const idx = arr.indexOf(fn);
    if (idx !== -1) arr.splice(idx, 1);
  };
}

/**
 * Batch-update multiple paths at once. Emits one "state:batch" event
 * after all individual "state:changed" events.
 * @param {Object} updates  e.g. { "chat.fsm": "sending", "session.tokens": 42 }
 */
function batch(updates) {
  const changes = [];
  for (const [path, value] of Object.entries(updates)) {
    const old = _deepGet(_state, path);
    if (old !== value) {
      set(path, value);
      changes.push({ path, value, old });
    }
  }
  if (changes.length > 0) {
    bus.emit('state:batch', changes);
  }
}

/**
 * Get a shallow snapshot of a state section (e.g. "chat", "health").
 * Returns a copy — mutations don't affect real state.
 */
function snapshot(section) {
  const val = section ? _state[section] : _state;
  if (val && typeof val === 'object') {
    return JSON.parse(JSON.stringify(val));
  }
  return val;
}

// ── Chat FSM convenience methods ─────────────────────────────────────────────
// These replace window.laylaChatFSM with proper state integration.

function chatCanSend() {
  const st = _state.chat.fsm;
  return st === ChatState.IDLE || st === ChatState.DONE || st === ChatState.ERROR;
}

function chatBeginSend() {
  if (!chatCanSend()) return false;
  set('chat.fsm', ChatState.SENDING);
  return true;
}

function chatBeginStream() {
  set('chat.fsm', ChatState.STREAMING);
}

function chatFinishOk() {
  set('chat.fsm', ChatState.DONE);
  // Brief DONE state so watchers can react, then → IDLE
  setTimeout(() => set('chat.fsm', ChatState.IDLE), 50);
}

function chatFinishError() {
  set('chat.fsm', ChatState.ERROR);
  setTimeout(() => set('chat.fsm', ChatState.IDLE), 50);
}

export const chatFSM = Object.freeze({
  canSend:      chatCanSend,
  beginSend:    chatBeginSend,
  beginStream:  chatBeginStream,
  finishOk:     chatFinishOk,
  finishError:  chatFinishError,
});

// ── Initialize from localStorage ─────────────────────────────────────────────
try {
  const savedConv = localStorage.getItem('layla_current_conversation_id') || '';
  if (savedConv) _state.chat.conversationId = savedConv;
} catch (_) {}

// ── Persist conversationId on change ─────────────────────────────────────────
watch('chat.conversationId', (val) => {
  try { localStorage.setItem('layla_current_conversation_id', val || ''); } catch (_) {}
});

export const appState = Object.freeze({
  get,
  set,
  watch,
  batch,
  snapshot,
  ChatState,
  chatFSM,
});

export default appState;

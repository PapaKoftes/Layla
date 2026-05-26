/**
 * core/bus.js — Central event bus for Layla UI.
 *
 * Replaces cross-module communication via window.* globals with a typed,
 * inspectable pub/sub system. All modules emit and subscribe through this
 * single bus instead of reaching into each other's internals.
 *
 * Usage:
 *   import { bus } from './core/bus.js';
 *   const off = bus.on('chat:message-sent', (data) => { ... });
 *   bus.emit('chat:message-sent', { text, aspect });
 *   off();  // unsubscribe
 *
 * Event naming: "domain:action" (e.g. "chat:send", "overlay:open", "health:update")
 */

const _listeners = new Map();
let _debugEnabled = false;

try {
  _debugEnabled = localStorage.getItem('layla_debug') === '1';
} catch (_) { /* SSR / restricted */ }

/**
 * Subscribe to an event.
 * @param {string} event
 * @param {Function} handler
 * @param {Object} [opts]
 * @param {boolean} [opts.once=false]  Auto-unsubscribe after first fire
 * @returns {Function} unsubscribe function
 */
function on(event, handler, opts) {
  if (typeof handler !== 'function') {
    throw new TypeError(`bus.on("${event}"): handler must be a function`);
  }
  if (!_listeners.has(event)) {
    _listeners.set(event, []);
  }
  const entry = { fn: handler, once: !!(opts && opts.once) };
  _listeners.get(event).push(entry);

  // Return unsubscribe function
  return function off() {
    const arr = _listeners.get(event);
    if (!arr) return;
    const idx = arr.indexOf(entry);
    if (idx !== -1) arr.splice(idx, 1);
    if (arr.length === 0) _listeners.delete(event);
  };
}

/**
 * Subscribe once — auto-unsubscribes after first fire.
 */
function once(event, handler) {
  return on(event, handler, { once: true });
}

/**
 * Emit an event. Handlers called synchronously in subscription order.
 * @param {string} event
 * @param {*} [data]
 */
function emit(event, data) {
  if (_debugEnabled) {
    console.log(`%c[bus] ${event}`, 'color:#7c5cbf;font-weight:bold', data);
  }
  const arr = _listeners.get(event);
  if (!arr || arr.length === 0) return;

  // Snapshot to avoid mutation during iteration
  const snapshot = arr.slice();
  for (let i = 0; i < snapshot.length; i++) {
    const entry = snapshot[i];
    try {
      entry.fn(data);
    } catch (err) {
      console.error(`[bus] handler error on "${event}":`, err);
    }
    if (entry.once) {
      const idx = arr.indexOf(entry);
      if (idx !== -1) arr.splice(idx, 1);
    }
  }
  if (arr.length === 0) _listeners.delete(event);
}

/**
 * Remove all listeners for a specific event, or all events.
 */
function clear(event) {
  if (event) {
    _listeners.delete(event);
  } else {
    _listeners.clear();
  }
}

/**
 * Debug: list all active subscriptions.
 */
function inspect() {
  const out = {};
  for (const [event, arr] of _listeners) {
    out[event] = arr.length;
  }
  return out;
}

/**
 * Enable or disable debug logging of all events.
 */
function setDebug(enabled) {
  _debugEnabled = !!enabled;
}

export const bus = Object.freeze({
  on,
  once,
  emit,
  clear,
  inspect,
  setDebug,
});

export default bus;

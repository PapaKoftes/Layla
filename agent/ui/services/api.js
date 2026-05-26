/**
 * services/api.js — Unified API layer for Layla UI.
 *
 * Replaces the monkey-patched window.fetch in layla-bootstrap.js and the
 * scattered fetch() calls across 31 files. Provides:
 *   - Automatic Bearer token injection for remote hosts
 *   - Request timeout with AbortController
 *   - Typed response handling (json, text, stream)
 *   - Request deduplication for polling endpoints
 *   - Centralized error formatting
 *
 * Usage:
 *   import { api } from './services/api.js';
 *   const health = await api.get('/health');
 *   const resp = await api.post('/agent', { message: '...' });
 *   const stream = await api.stream('/agent', { message: '...' });
 */

import { bus } from '../core/bus.js';

// ── Configuration ────────────────────────────────────────────────────────────
const _config = {
  defaultTimeout:  12000,
  agentTimeout:    120000,
  baseUrl:         '',       // empty = same origin
};

// ── Remote auth ──────────────────────────────────────────────────────────────
function _isNonLocalHost() {
  try {
    const h = location.hostname || '';
    return h && h !== '127.0.0.1' && h !== 'localhost';
  } catch (_) { return false; }
}

function _getAuthHeader() {
  try {
    const key = localStorage.getItem('layla_remote_api_key') || '';
    return key ? `Bearer ${key}` : null;
  } catch (_) { return null; }
}

// ── In-flight dedup for GET requests ─────────────────────────────────────────
const _inFlight = new Map();

// ── Core request function ────────────────────────────────────────────────────
/**
 * Make an HTTP request with timeout and auth.
 *
 * @param {string} url       Absolute or relative URL
 * @param {Object} [opts]
 * @param {string} [opts.method='GET']
 * @param {Object} [opts.body]           Auto-serialized to JSON
 * @param {Object} [opts.headers]        Additional headers
 * @param {number} [opts.timeout]        Timeout in ms (default: 12000)
 * @param {AbortSignal} [opts.signal]    External abort signal
 * @param {boolean} [opts.dedup=false]   Deduplicate concurrent identical GETs
 * @param {string} [opts.responseType='json']  'json' | 'text' | 'response'
 * @returns {Promise<*>}
 */
async function request(url, opts) {
  opts = opts || {};
  const method = (opts.method || 'GET').toUpperCase();
  const timeout = opts.timeout || (method === 'POST' ? _config.agentTimeout : _config.defaultTimeout);
  const responseType = opts.responseType || 'json';

  // Dedup for identical in-flight GETs
  if (method === 'GET' && opts.dedup !== false) {
    const key = url;
    if (_inFlight.has(key)) {
      return _inFlight.get(key);
    }
  }

  // Build headers
  const headers = new Headers(opts.headers || undefined);
  if (opts.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // Inject auth for remote hosts
  if (_isNonLocalHost() && url.charAt(0) === '/') {
    const bearer = _getAuthHeader();
    if (bearer && !headers.has('Authorization')) {
      headers.set('Authorization', bearer);
    }
  }

  // Timeout via AbortController
  const timeoutCtrl = new AbortController();
  const timer = setTimeout(() => {
    try { timeoutCtrl.abort(); } catch (_) {}
  }, timeout);

  // Link external signal with timeout
  const linked = new AbortController();
  function abortLinked() {
    try { linked.abort(); } catch (_) {}
  }
  timeoutCtrl.signal.addEventListener('abort', abortLinked);
  if (opts.signal) {
    if (opts.signal.aborted) abortLinked();
    else opts.signal.addEventListener('abort', abortLinked);
  }

  const fetchOpts = {
    method,
    headers,
    signal: linked.signal,
    cache: opts.cache || (method === 'GET' ? 'no-store' : undefined),
  };

  if (opts.body && method !== 'GET') {
    fetchOpts.body = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
  }

  const promise = (async () => {
    try {
      const response = await fetch(_config.baseUrl + url, fetchOpts);

      if (responseType === 'response') return response;

      if (!response.ok) {
        let errorBody;
        try { errorBody = await response.json(); } catch (_) {
          try { errorBody = await response.text(); } catch (__) { errorBody = null; }
        }
        const err = new Error(formatError(response, errorBody));
        err.status = response.status;
        err.body = errorBody;
        throw err;
      }

      if (responseType === 'text') return response.text();
      return response.json();
    } finally {
      clearTimeout(timer);
      try { timeoutCtrl.signal.removeEventListener('abort', abortLinked); } catch (_) {}
      if (opts.signal) {
        try { opts.signal.removeEventListener('abort', abortLinked); } catch (_) {}
      }
      // Remove from dedup map
      if (method === 'GET') {
        _inFlight.delete(url);
      }
    }
  })();

  // Register for dedup
  if (method === 'GET' && opts.dedup !== false) {
    _inFlight.set(url, promise);
  }

  return promise;
}

// ── Convenience methods ──────────────────────────────────────────────────────
function get(url, opts) {
  return request(url, { ...opts, method: 'GET' });
}

function post(url, body, opts) {
  return request(url, { ...opts, method: 'POST', body });
}

function put(url, body, opts) {
  return request(url, { ...opts, method: 'PUT', body });
}

function del(url, opts) {
  return request(url, { ...opts, method: 'DELETE' });
}

/**
 * Start an SSE stream. Returns the raw Response for manual reading.
 *
 * @param {string} url
 * @param {Object} body
 * @param {Object} [opts]
 * @returns {Promise<Response>}
 */
function stream(url, body, opts) {
  return request(url, {
    ...opts,
    method: 'POST',
    body,
    responseType: 'response',
    timeout: opts?.timeout || _config.agentTimeout,
  });
}

// ── Error formatting ─────────────────────────────────────────────────────────
function formatError(res, body) {
  if (!res) return "Can't reach Layla. Is the server running at http://127.0.0.1:8000?";
  if (res.status === 500) return 'Something went wrong. Check the server logs or try again.';
  if (res.status === 503) return (body && body.detail) || 'Service temporarily unavailable.';
  const err = body && (body.detail || body.response || body.message);
  if (err && String(err).length < 200) return String(err);
  return 'Request failed: ' + res.status;
}

// ── Configuration API ────────────────────────────────────────────────────────
function configure(opts) {
  if (opts.defaultTimeout != null) _config.defaultTimeout = opts.defaultTimeout;
  if (opts.agentTimeout != null)   _config.agentTimeout = opts.agentTimeout;
  if (opts.baseUrl != null)        _config.baseUrl = opts.baseUrl;
}

/**
 * Get the configured agent timeout in ms.
 */
function getAgentTimeout() {
  try {
    const stored = parseInt(localStorage.getItem('layla_agent_timeout_ms') || '', 10);
    return (stored > 0 && stored <= 600000) ? stored : _config.agentTimeout;
  } catch (_) { return _config.agentTimeout; }
}

export const api = Object.freeze({
  request,
  get,
  post,
  put,
  del,
  stream,
  formatError,
  configure,
  getAgentTimeout,
});

export default api;

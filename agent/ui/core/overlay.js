/**
 * core/overlay.js — Unified overlay manager for Layla UI.
 *
 * Replaces 8 competing overlay systems (setup z:10000, wizard z:10002,
 * onboarding z:10003, settings z:9000, tutorial z:4000, character-lab z:3000,
 * right-panel z:210, rank-up z:9998, diff z:10000) with a single managed stack.
 *
 * Each overlay registers once with a priority tier. Only one overlay per tier
 * can be active. Higher tiers always render above lower tiers.
 * Escape key closes the topmost overlay.
 *
 * Usage:
 *   import { overlayManager } from './core/overlay.js';
 *
 *   overlayManager.register('settings', {
 *     tier: 'panel',
 *     elementId: 'settings-overlay',
 *     onOpen: (el) => { ... },
 *     onClose: (el) => { ... },
 *     escapable: true,
 *   });
 *
 *   overlayManager.open('settings');
 *   overlayManager.close('settings');
 *   overlayManager.toggle('settings');
 */

import { bus } from './bus.js';
import { appState } from './state.js';

// ── Tier z-index assignments ─────────────────────────────────────────────────
// Strict ordering prevents z-index wars. Each tier gets a fixed base z-index.
const TIERS = Object.freeze({
  panel:      200,     // Right panel, side drawers
  modal:      5000,    // Settings, diff viewer
  wizard:     7000,    // Setup wizard, onboarding
  system:     9000,    // Critical system overlays (setup, pairing)
  alert:      9500,    // Rank-up celebrations, warnings
  blocking:  10000,    // Full-screen blocking (error, first-run)
});

// ── Registry ─────────────────────────────────────────────────────────────────
const _registry = new Map();

// Active overlay IDs ordered by open time (most recent last)
const _activeStack = [];

/**
 * Register an overlay.
 *
 * @param {string} id             Unique overlay identifier
 * @param {Object} config
 * @param {string} config.tier    One of: panel, modal, wizard, system, alert, blocking
 * @param {string} [config.elementId]  DOM element ID (auto-show/hide via class)
 * @param {Function} [config.onOpen]   Called with (element) when opened
 * @param {Function} [config.onClose]  Called with (element) when closed
 * @param {boolean} [config.escapable=true]  Close on Escape key
 * @param {boolean} [config.backdrop=true]   Show backdrop (for tiers above panel)
 */
function register(id, config) {
  if (!config || !config.tier) {
    throw new Error(`overlay.register("${id}"): tier is required`);
  }
  if (!(config.tier in TIERS)) {
    throw new Error(`overlay.register("${id}"): unknown tier "${config.tier}". Valid: ${Object.keys(TIERS).join(', ')}`);
  }
  _registry.set(id, {
    tier:       config.tier,
    elementId:  config.elementId || id,
    onOpen:     config.onOpen || null,
    onClose:    config.onClose || null,
    escapable:  config.escapable !== false,
    backdrop:   config.backdrop !== false,
  });
}

/**
 * Open an overlay. Closes any existing overlay in the same tier.
 */
function open(id, data) {
  const config = _registry.get(id);
  if (!config) {
    console.warn(`[overlay] "${id}" not registered`);
    return false;
  }

  // Close any overlay in the same tier
  for (let i = _activeStack.length - 1; i >= 0; i--) {
    const activeId = _activeStack[i];
    const activeConfig = _registry.get(activeId);
    if (activeConfig && activeConfig.tier === config.tier && activeId !== id) {
      close(activeId);
    }
  }

  // If already open, no-op
  if (_activeStack.includes(id)) return true;

  // Get DOM element
  const el = document.getElementById(config.elementId);

  // Apply z-index from tier
  if (el) {
    const tierZ = TIERS[config.tier];
    el.style.zIndex = String(tierZ);
    el.classList.add('overlay-active');
    el.classList.add('visible');
    el.style.display = '';
    el.removeAttribute('hidden');
    el.setAttribute('aria-hidden', 'false');
  }

  // Show backdrop if needed
  if (config.backdrop && config.tier !== 'panel') {
    _ensureBackdrop(TIERS[config.tier] - 1);
  }

  // Push to stack
  _activeStack.push(id);

  // Update state
  appState.set('overlay.stack', _activeStack.slice());

  // Call open handler
  if (config.onOpen) {
    try { config.onOpen(el, data); } catch (e) {
      console.error(`[overlay] onOpen error for "${id}":`, e);
    }
  }

  // Emit event
  bus.emit('overlay:opened', { id, tier: config.tier, data });

  // Manage body scroll lock
  _updateBodyScrollLock();

  return true;
}

/**
 * Close an overlay.
 */
function close(id) {
  const config = _registry.get(id);
  if (!config) return false;

  const idx = _activeStack.indexOf(id);
  if (idx === -1) return false; // not open

  // Remove from stack
  _activeStack.splice(idx, 1);

  // Get DOM element
  const el = document.getElementById(config.elementId);
  if (el) {
    el.classList.remove('overlay-active');
    el.classList.remove('visible');
    el.setAttribute('aria-hidden', 'true');
    // Don't set display:none — let CSS handle visibility via the class
  }

  // Update state
  appState.set('overlay.stack', _activeStack.slice());

  // Call close handler
  if (config.onClose) {
    try { config.onClose(el); } catch (e) {
      console.error(`[overlay] onClose error for "${id}":`, e);
    }
  }

  // Emit event
  bus.emit('overlay:closed', { id, tier: config.tier });

  // Update backdrop and scroll lock
  _updateBackdrop();
  _updateBodyScrollLock();

  return true;
}

/**
 * Toggle an overlay open/closed.
 */
function toggle(id, data) {
  if (isOpen(id)) {
    return close(id);
  }
  return open(id, data);
}

/**
 * Check if an overlay is currently open.
 */
function isOpen(id) {
  return _activeStack.includes(id);
}

/**
 * Get the topmost overlay ID, or null.
 */
function topmost() {
  return _activeStack.length > 0 ? _activeStack[_activeStack.length - 1] : null;
}

/**
 * Close the topmost escapable overlay. Called by Escape key handler.
 * @returns {boolean} true if an overlay was closed
 */
function closeTopmost() {
  for (let i = _activeStack.length - 1; i >= 0; i--) {
    const id = _activeStack[i];
    const config = _registry.get(id);
    if (config && config.escapable) {
      close(id);
      return true;
    }
  }
  return false;
}

/**
 * Close all overlays.
 */
function closeAll() {
  const ids = _activeStack.slice().reverse();
  for (const id of ids) {
    close(id);
  }
}

/**
 * Get a list of all registered overlay IDs.
 */
function listRegistered() {
  return Array.from(_registry.keys());
}

// ── Backdrop management ──────────────────────────────────────────────────────
let _backdropEl = null;

function _ensureBackdrop(zIndex) {
  if (!_backdropEl) {
    _backdropEl = document.createElement('div');
    _backdropEl.id = 'overlay-manager-backdrop';
    _backdropEl.className = 'overlay-backdrop';
    _backdropEl.addEventListener('click', () => {
      closeTopmost();
    });
    document.body.appendChild(_backdropEl);
  }
  _backdropEl.style.zIndex = String(zIndex);
  _backdropEl.classList.add('visible');
  _backdropEl.setAttribute('aria-hidden', 'false');
}

function _updateBackdrop() {
  if (!_backdropEl) return;

  // Find highest tier that needs backdrop
  let highestBackdropZ = -1;
  for (const id of _activeStack) {
    const config = _registry.get(id);
    if (config && config.backdrop && config.tier !== 'panel') {
      const z = TIERS[config.tier] - 1;
      if (z > highestBackdropZ) highestBackdropZ = z;
    }
  }

  if (highestBackdropZ < 0) {
    _backdropEl.classList.remove('visible');
    _backdropEl.setAttribute('aria-hidden', 'true');
  } else {
    _backdropEl.style.zIndex = String(highestBackdropZ);
    _backdropEl.classList.add('visible');
    _backdropEl.setAttribute('aria-hidden', 'false');
  }
}

function _updateBodyScrollLock() {
  // Lock scroll if any overlay above 'panel' tier is open
  const hasHighOverlay = _activeStack.some(id => {
    const config = _registry.get(id);
    return config && TIERS[config.tier] >= TIERS.modal;
  });
  document.body.classList.toggle('overlay-scroll-lock', hasHighOverlay);
}

// ── Global Escape key handler ────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && _activeStack.length > 0) {
    if (closeTopmost()) {
      e.preventDefault();
      e.stopPropagation();
    }
  }
}, true); // capture phase

export const overlayManager = Object.freeze({
  TIERS,
  register,
  open,
  close,
  toggle,
  isOpen,
  topmost,
  closeTopmost,
  closeAll,
  listRegistered,
});

export default overlayManager;

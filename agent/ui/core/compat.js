/**
 * core/compat.js — Backward-compatibility bridge (TRIMMED).
 *
 * Exposes ES module APIs onto window.* for two remaining use cases:
 *   A) Cross-module window.* calls — where one module calls a function
 *      from another module via the window global (not yet converted to
 *      direct imports or bus events).
 *   B) Dynamic onclick in JS — where JS code builds HTML strings
 *      containing onclick="fn(...)" which requires fn on window.*.
 *
 * ~140 shims removed in Phase 6 (inline HTML handlers converted to
 * data-action delegation in Phase 5). Infrastructure bridges (bus.on,
 * appState.watch, dashboard cards, FSM compat) are permanent.
 *
 * This file is imported by main.js AFTER all core modules are loaded.
 */

import { bus } from './bus.js';
import { appState, ChatState, chatFSM } from './state.js';
import { overlayManager } from './overlay.js';
import { api } from '../services/api.js';
import { healthService } from '../services/health.js';

// ── Module imports (only functions still needed on window.*) ─────────────

import { LaylaUI } from '../components/ui-phases.js';
import { setAspectSprite } from '../components/sprites.js';
import { scrollActiveConversationIntoView } from '../components/sidebar.js';

import { cleanLaylaText, sanitizeHtml } from '../services/utils.js';

import {
  ASPECTS, formatLaylaLabelHtml,
  setAspect, refreshMaturityCard, refreshOptionDependencies,
} from '../components/aspect.js';

import { speakText } from '../components/voice.js';

import {
  showMemorySubTab, laylaMemBrowse, laylaMemEdit, laylaMemCancelEdit,
  laylaMemSaveEdit, laylaMemDelete,
} from '../components/memory.js';

import {
  laylaArtifactsScan, laylaIngestArtifacts,
  laylaArtifactCopy, laylaArtifactEdit, laylaArtifactRemove,
} from '../components/artifacts.js';

import {
  laylaSearchOpenConv, laylaSearchOpenMemory,
  laylaSearchOpenWorkspace, laylaSearchOpenKnowledge,
  laylaGlobalSearchInput,
} from '../components/search.js';

import { laylaShowPlanViz } from '../components/plan-viz.js';

import { refreshClusterStatus } from '../components/cluster.js';
import { refreshGrowthDashboard } from '../components/growth.js';

import {
  initiatePairing, closePinDialog, unpairDevice, checkPeerHealth, toggleDevicePermission,
} from '../components/pairing.js';

import {
  checkSetupStatus, loadSetupCatalog,
  dismissSetupOverlay, dismissTour, maybeStartTour,
} from '../components/setup.js';

// BL-249: #onboarding-overlay (the chat interview) belongs to onboarding.js — so its close (Escape / the
// overlay manager) goes through its OWN dismiss, not the tour's. The tour lives at #tour-overlay.
import { dismissOnboarding } from '../components/onboarding.js';

import {
  triggerSend, hideKeyboardShortcutsSheet,
  showMainPanel, showWorkspaceSubtab,
} from '../components/bootstrap.js';

import {
  refreshMissionStatus, refreshApprovals, showResearchTab,
  laylaRunAutonomousResearch,
} from '../components/research.js';

import {
  refreshWorkspacePresetsDropdown, refreshRelationshipCodex,
} from '../components/settings-full.js';

import {
  updateContextChip, toggleChatRailMobile, loadProjectsIntoSelect,
} from '../components/conversations.js';

import {
  closeRightPanel as closeRightPanelInput, fillPrompt,
  closeDiffViewer, closeBatchDiffViewer,
} from '../components/input.js';

import {
  addStudyPlan, laylaApprovePlan, laylaExecutePlan, laylaExpandPlan,
  cancelBackgroundTask, workspaceSubtabRefresh,
} from '../components/workspace.js';

import {
  UX_STATE_LABELS,
  laylaNotifyStreamPhase, laylaApplyUiTimeoutsFromHealth,
  laylaAgentStreamTimeoutMs, laylaStalledSilenceMs,
  laylaHeaderProgressStart, laylaHeaderProgressStop,
  operatorTraceLine,
  hideEmpty, renderPromptTilesAndEmptyState,
  addMsg, addSeparator,
  laylaStartNonStreamTypingPhases,
  laylaRemoveTypingIndicator, laylaShowTypingIndicator,
  retryLastMessage, laylaOnChatState,
  toggleSendButton,
} from '../components/chat-render.js';

import {
  ensureLaylaConversationId, executePlan, send,
  refreshContentPolicyToggles,
} from '../components/app.js';


// ══════════════════════════════════════════════════════════════════════════════
// INFRASTRUCTURE BRIDGES (permanent — not shims)
// ══════════════════════════════════════════════════════════════════════════════

// ── Bus on window ────────────────────────────────────────────────────────────
window.__laylaBus = bus;

// ── State on window ─────────────────────────────────────────────────────────
window.__laylaState = appState;

// ── Chat FSM compat (replaces state.js IIFE) ────────────────────────────────
// Old code uses: window.LaylaChatState, window.laylaChatFSM
window.LaylaChatState = ChatState;
window.laylaChatFSM = {
  getState:    () => appState.get('chat.fsm'),
  canSend:     chatFSM.canSend,
  beginSend:   chatFSM.beginSend,
  beginStream: chatFSM.beginStream,
  finishOk:    chatFSM.finishOk,
  finishError: chatFSM.finishError,
  transition:  (next) => appState.set('chat.fsm', next),
};

// Wire laylaOnChatState callback bridge
appState.watch('chat.fsm', (val) => {
  try {
    if (typeof window.laylaOnChatState === 'function') {
      window.laylaOnChatState(val);
    }
  } catch (_) {}
});

// ── Overlay manager on window ───────────────────────────────────────────────
window.__laylaOverlay = overlayManager;

// ── API service on window ───────────────────────────────────────────────────
window.__laylaApi = api;

// Old code uses: window.laylaApiJson
window.laylaApiJson = function (url, opts) {
  opts = opts || {};
  return fetch(url, opts).then(function (r) {
    return r.json().then(function (j) {
      return { ok: r.ok, status: r.status, json: j };
    });
  });
};

// Old code uses: window.fetchWithTimeout
window.fetchWithTimeout = async function (url, options, timeoutMs) {
  try {
    const resp = await api.request(url, {
      ...(options || {}),
      method: (options && options.method) || 'GET',
      timeout: timeoutMs || 12000,
      responseType: 'response',
      dedup: false,
    });
    return resp;
  } catch (e) {
    throw e;
  }
};

// Old code uses: window.formatAgentError
window.formatAgentError = api.formatError;

// Old code uses: window.laylaAgentTimeoutMs
window.laylaAgentTimeoutMs = api.getAgentTimeout;

// ── Health service on window ────────────────────────────────────────────────
window.__laylaHealth = window.__laylaHealth || {};
window.__laylaHealthService = healthService;

// Bridge health updates to old DOM-manipulation code
bus.on('health:deep-update', (d) => {
  window.__laylaHealth.payload = d;
  window.__laylaHealth.lastDeepFetch = Date.now();
});

// Bridge dashboard poll start/stop (old visibility handler references)
window._laylaStartDashPoll = () => healthService.resume();
window._laylaStopDashPoll  = () => healthService.pause();

// ── Conversation ID compat ──────────────────────────────────────────────────
// Old code reads/writes window.currentConversationId directly.
// Capture any value set by legacy code before we replace with getter/setter.
{
  const _existingConvId = window.currentConversationId || '';
  if (_existingConvId) appState.set('chat.conversationId', _existingConvId);
  Object.defineProperty(window, 'currentConversationId', {
    get() { return appState.get('chat.conversationId') || ''; },
    set(val) { appState.set('chat.conversationId', val || ''); },
    configurable: true,
  });
}

// Old code reads/writes window.currentAspect directly.
{
  const _existingAspect = window.currentAspect || 'morrigan';
  if (_existingAspect !== 'morrigan') appState.set('aspect.current', _existingAspect);
  Object.defineProperty(window, 'currentAspect', {
    get() { return appState.get('aspect.current') || 'morrigan'; },
    set(val) {
      appState.set('aspect.current', val || 'morrigan');
    },
    configurable: true,
  });
}

// ── Session time bridge ─────────────────────────────────────────────────────
bus.on('session:time-tick', ({ formatted }) => {
  const el = document.getElementById('session-time');
  if (el) el.textContent = formatted;
});

// ── Health status badge bridge ──────────────────────────────────────────────
bus.on('health:deep-update', (d) => {
  // Update hidden header badges (MutationObserver syncs to topbar)
  const el = document.getElementById('header-system-status');
  if (!el) return;

  const mode = d.remote_mode ? 'remote' : 'local';
  const raw = String(d.active_model || d.model_path || d.model || d.model_filename || '').trim();
  let tail = raw;
  if (tail) {
    const i = Math.max(tail.lastIndexOf('/'), tail.lastIndexOf('\\'));
    if (i >= 0) tail = tail.slice(i + 1);
    tail = tail.replace(/\.gguf$/i, '');   // drop the redundant extension (was cut to ".g")
    // Middle-ellipsize so BOTH the name and the meaningful quant (…Q4_K_M) survive.
    if (tail.length > 30) tail = tail.slice(0, 16) + '…' + tail.slice(-12);
  }
  el.textContent = mode + (tail ? ' · ' + tail : '');
  el.title = raw || '';

  // Model status badge
  const msb = document.getElementById('model-status-badge');
  if (msb) {
    msb.textContent = d.model_loaded ? '● Model OK' : '○ No model';
    msb.title = d.model_loaded ? ('Model loaded' + (raw ? ': ' + raw : '')) : 'No model loaded';
    msb.style.color = d.model_loaded ? 'var(--success)' : 'var(--text-dim)';
  }
});

// Connection banner bridge
bus.on('health:connected', () => {
  const ban = document.getElementById('connection-banner');
  if (ban) ban.style.display = 'none';
});

bus.on('health:disconnected', () => {
  const ban = document.getElementById('connection-banner');
  if (ban) ban.style.display = 'block';
});

// ── Session stats badge bridge ──────────────────────────────────────────────
bus.on('session:stats-update', (stats) => {
  const t = document.getElementById('header-session-tokens');
  if (!t) return;
  const tt = stats.total_tokens || 0;
  const tc = stats.tool_calls || 0;
  const elapsed = stats.elapsed_seconds || 0;
  t.textContent = `Σ ${tt} tok · ${tc} tools · ${elapsed}s`;
  t.title = `GET /session/stats — prompt:${stats.prompt_tokens ?? '?'} completion:${stats.completion_tokens ?? '?'}`;
});

// ── Context row bridge ──────────────────────────────────────────────────────
appState.watch('chat.conversationId', (cid) => {
  const el = document.getElementById('header-conv-id');
  if (!el) return;
  el.textContent = cid ? ('conv ' + cid.slice(0, 8)) : 'new chat';
  el.title = cid ? ('conversation_id: ' + cid) : 'No conversation id yet';
});

// ── Dashboard cards bridge ──────────────────────────────────────────────────
function _dashSetVal(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text || '—';
}

function _formatUptime(s) {
  if (!s || s < 0) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm ' + Math.floor(s % 60) + 's';
}

bus.on('health:deep-update', (d) => {
  _dashSetVal('dash-facts-val', String(d.learnings || 0));
  _dashSetVal('dash-uptime-val', _formatUptime(d.uptime_seconds));
  if (d.resource_load) {
    const mode = (d.resource_load.governor_mode || d.resource_load.mode || '').toLowerCase();
    if (mode) {
      _dashSetVal('dash-governor-val', mode.charAt(0).toUpperCase() + mode.slice(1));
      const card = document.getElementById('dash-governor');
      if (card) card.setAttribute('data-mode', mode);
    }
  }
});

bus.on('cluster:status-update', (d) => {
  const gm = (d.governor_mode || '').toLowerCase();
  if (gm && gm !== 'unknown') {
    _dashSetVal('dash-governor-val', gm.charAt(0).toUpperCase() + gm.slice(1));
    const card = document.getElementById('dash-governor');
    if (card) card.setAttribute('data-mode', gm);
  }
  // /cluster/status returns `enabled` + `peer_count` (+ a `peers` array). Read those — the old
  // `cluster_enabled` / `peers`-count / `node_role` names don't exist on the endpoint, so the card
  // always fell back to "Standalone"/"queen" even with a live cluster. Keep legacy fallbacks defensively.
  const _peersRaw = (d.peer_count != null ? d.peer_count : (d.peers != null ? d.peers : (d.connected_peers || 0)));
  const peerCount = typeof _peersRaw === 'number' ? _peersRaw :
    (Array.isArray(_peersRaw) ? _peersRaw.length : Object.keys(_peersRaw || {}).length);
  const role = (d.node_role || d.role || 'queen').toUpperCase();
  const clusterOn = (d.enabled != null ? d.enabled : d.cluster_enabled);
  if (clusterOn) {
    _dashSetVal('dash-cluster-val', role + ' · ' + peerCount + ' peer' + (peerCount !== 1 ? 's' : ''));
  } else {
    _dashSetVal('dash-cluster-val', 'Standalone');
  }
});

bus.on('growth:stats-update', (d) => {
  if (d.total_facts != null) {
    _dashSetVal('dash-facts-val', String(d.total_facts) +
      (d.high_confidence_facts ? ' (' + d.high_confidence_facts + ' verified)' : ''));
  }
});

bus.on('profile:update', (d) => {
  const mat = d.maturity || {};
  if (mat.rank != null) {
    let label = 'Rank ' + mat.rank;
    if (mat.phase) label += ' · ' + mat.phase.charAt(0).toUpperCase() + mat.phase.slice(1);
    _dashSetVal('dash-maturity-val', label);
  }
});


// ══════════════════════════════════════════════════════════════════════════════
// WINDOW.* SHIMS — cross-module calls (A) + dynamic onclick (B)
// ══════════════════════════════════════════════════════════════════════════════

// ── ui-phases.js ── (A: chat-render, research read LaylaUI)
window.LaylaUI = window.LaylaUI || {};
Object.assign(window.LaylaUI, LaylaUI);

// ── sprites.js ── (A: aspect.js calls laylaSetAspectSprite)
window.laylaSetAspectSprite = setAspectSprite;

// ── sidebar.js ── (A: app.js, conversations.js call it)
window.laylaScrollActiveConversationIntoView = scrollActiveConversationIntoView;

// ── utils.js ── (A: research.js, app.js call these cross-module)
window.cleanLaylaText = cleanLaylaText;
window.sanitizeHtml = sanitizeHtml;

// ── aspect.js ── (A: multiple modules read ASPECTS, setAspect, etc.)
window.ASPECTS = ASPECTS;
window.formatLaylaLabelHtml = formatLaylaLabelHtml;
window.setAspect = setAspect;
window.refreshMaturityCard = refreshMaturityCard;
window.refreshOptionDependencies = refreshOptionDependencies;

// ── voice.js ── (A: app.js, perf.js call speakText)
window.speakText = speakText;

// ── memory.js ── (A: search.js + B: dynamic onclick in memory.js)
window.showMemorySubTab = showMemorySubTab;
window.laylaMemBrowse = laylaMemBrowse;
window.laylaMemEdit = laylaMemEdit;
window.laylaMemCancelEdit = laylaMemCancelEdit;
window.laylaMemSaveEdit = laylaMemSaveEdit;
window.laylaMemDelete = laylaMemDelete;

// ── artifacts.js ── (A: app.js, perf.js + B: dynamic onclick in artifacts.js)
window.laylaArtifactsScan = laylaArtifactsScan;
window.laylaIngestArtifacts = laylaIngestArtifacts;
window.laylaArtifactCopy = laylaArtifactCopy;
window.laylaArtifactEdit = laylaArtifactEdit;
window.laylaArtifactRemove = laylaArtifactRemove;

// ── search.js ── (B: dynamic onclick in search.js result rendering)
window.laylaSearchOpenConv = laylaSearchOpenConv;
window.laylaSearchOpenMemory = laylaSearchOpenMemory;
window.laylaSearchOpenWorkspace = laylaSearchOpenWorkspace;
window.laylaSearchOpenKnowledge = laylaSearchOpenKnowledge;
// index.html search input calls this inline via onfocus — bridge it so focus doesn't throw
// ReferenceError (typing already routes through the data-on-input delegated action).
window.laylaGlobalSearchInput = laylaGlobalSearchInput;

// ── plan-viz.js ── (B: dynamic onclick in workspace.js)
window.laylaShowPlanViz = laylaShowPlanViz;

// ── cluster.js ── (A: app.js calls refreshClusterStatus)
window.refreshClusterStatus = refreshClusterStatus;

// ── growth.js ── (A: app.js calls refreshGrowthDashboard)
window.refreshGrowthDashboard = refreshGrowthDashboard;

// ── pairing.js ── (B: dynamic onclick in pairing.js peer cards)
window.initiatePairing = initiatePairing;
window.closePinDialog = closePinDialog;
window.unpairDevice = unpairDevice;
window.checkPeerHealth = checkPeerHealth;
// A2. The paired-device card renders onchange="toggleDevicePermission(...)" and this export was
// missing, so every permission checkbox on that card threw ReferenceError and did NOTHING —
// including `remote_tools`, which grants remote tool execution. Driven in a real browser: the
// box ticked, no request was sent, and the server's stored permissions never changed. The two
// buttons on the same card (Unpair, Ping) were exported and worked, which is what kept the gap
// invisible. Any function this module names in generated markup has to be listed here.
window.toggleDevicePermission = toggleDevicePermission;

// ── setup.js ── (A: app.js, wizard.js + B: dynamic onclick)
window.checkSetupStatus = checkSetupStatus;
window.loadSetupCatalog = loadSetupCatalog;
window.dismissSetupOverlay = dismissSetupOverlay;
// #onboarding-overlay (interview) closes via onboarding.js; #tour-overlay (first-run tour) via setup.js.
window.dismissOnboarding = dismissOnboarding;
window.dismissTour = dismissTour;
// BL-249: the wizard hands off to the tour when it finishes (wizard.js onNext, step 5).
window.maybeStartTour = maybeStartTour;

// ── bootstrap.js ── (A: bootstrap.js self-ref, input.js, search.js)
window.triggerSend = triggerSend;
window.hideKeyboardShortcutsSheet = hideKeyboardShortcutsSheet;  // index.html inline onclick (overlay dismiss)
window.showMainPanel = showMainPanel;
window.showWorkspaceSubtab = showWorkspaceSubtab;

// ── research.js ── (A: app.js, input.js, autonomous.js call these)
window.refreshMissionStatus = refreshMissionStatus;
window.refreshApprovals = refreshApprovals;
window.showResearchTab = showResearchTab;
window.laylaRunAutonomousResearch = laylaRunAutonomousResearch;

// ── settings-full.js ── (A: app.js, workspace.js call these)
window.refreshWorkspacePresetsDropdown = refreshWorkspacePresetsDropdown;
window.refreshRelationshipCodex = refreshRelationshipCodex;

// ── conversations.js ── (A: app.js, aspect.js, workspace.js, bootstrap.js)
window.updateContextChip = updateContextChip;
window.toggleChatRailMobile = toggleChatRailMobile;
window.loadProjectsIntoSelect = loadProjectsIntoSelect;

// ── input.js ── (A: bootstrap.js + B: dynamic onclick + index.html inline)
window.closeRightPanel = closeRightPanelInput;
window.fillPrompt = fillPrompt;                  // B: chat-render.js dynamic onclick
window.closeDiffViewer = closeDiffViewer;        // index.html inline onclick (overlay dismiss)
window.closeBatchDiffViewer = closeBatchDiffViewer; // index.html inline onclick (overlay dismiss)

// ── workspace.js ── (A: app.js, bootstrap.js + B: dynamic onclick)
window.addStudyPlan = addStudyPlan;
window.laylaApprovePlan = laylaApprovePlan;
window.laylaExecutePlan = laylaExecutePlan;
window.laylaExpandPlan = laylaExpandPlan;
window.cancelBackgroundTask = cancelBackgroundTask;
window.__laylaRefreshAfterWorkspaceSubtab = workspaceSubtabRefresh;

// ── chat-render.js ── (A: research.js, app.js, conversations.js, input.js, etc.)
window.UX_STATE_LABELS = UX_STATE_LABELS;
window.laylaNotifyStreamPhase = laylaNotifyStreamPhase;
window.laylaApplyUiTimeoutsFromHealth = laylaApplyUiTimeoutsFromHealth;
window.laylaAgentStreamTimeoutMs = laylaAgentStreamTimeoutMs;
window.laylaStalledSilenceMs = laylaStalledSilenceMs;
window.laylaHeaderProgressStart = laylaHeaderProgressStart;
window.laylaHeaderProgressStop = laylaHeaderProgressStop;
window.operatorTraceLine = operatorTraceLine;
window.hideEmpty = hideEmpty;
window.renderPromptTilesAndEmptyState = renderPromptTilesAndEmptyState;
window.addMsg = addMsg;
window.addSeparator = addSeparator;
window.laylaStartNonStreamTypingPhases = laylaStartNonStreamTypingPhases;
window.laylaRemoveTypingIndicator = laylaRemoveTypingIndicator;
window.laylaShowTypingIndicator = laylaShowTypingIndicator;
window.retryLastMessage = retryLastMessage;
window.laylaOnChatState = laylaOnChatState;
window.toggleSendButton = toggleSendButton;

// ── app.js ── (A: bootstrap.js, chat-render.js, voice.js, workspace.js)
window.ensureLaylaConversationId = ensureLaylaConversationId;
window.executePlan = executePlan;
window.send = send;
window.refreshContentPolicyToggles = refreshContentPolicyToggles;

// ── Mark compat as loaded ───────────────────────────────────────────────────
window.__laylaCompatLoaded = true;

console.log('[Layla] core/compat.js loaded — ES module bridge active (trimmed)');

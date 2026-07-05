/**
 * main.js — ES Module entry point for Layla UI.
 *
 * This is the single <script type="module"> entry point that replaces the
 * chain of 31 <script> tags. During migration, it coexists with the legacy
 * scripts — the compat bridge exposes new APIs onto window.* so old code
 * still works.
 *
 * Migration phases:
 *   Phase 1 (current): main.js loads core modules + compat bridge.
 *                       Legacy scripts still load via <script> tags.
 *   Phase 2: Convert modules one-by-one from IIFE → ES import.
 *            Each converted module gets its <script> tag removed.
 *   Phase 3: All modules converted. Remove compat bridge.
 *            Single <script type="module" src="main.js"> remains.
 *
 * Execution order (important!):
 *   <script type="module"> is deferred — it runs AFTER all synchronous
 *   <script> tags. This means legacy IIFEs execute first and set their
 *   window.* globals. Then this module runs and the compat bridge
 *   overwrites those globals with module-backed versions. This is safe:
 *   - Old globals are replaced with reactive proxies to appState
 *   - Any values already set by legacy code are read during init
 *   - The health service takes over polling from layla-app.js
 *
 * Internal load order (ES module graph):
 *   1. core/bus.js       — Event bus (no deps)
 *   2. core/state.js     — Centralized state (depends on bus)
 *   3. core/overlay.js   — Overlay manager (depends on bus + state)
 *   4. services/api.js   — API layer (depends on bus)
 *   5. services/health.js— Health polling (depends on bus + state + api)
 *   6. core/compat.js    — Window.* bridge (depends on all above)
 *   7. Start services
 */

// ── Core imports ─────────────────────────────────────────────────────────────
import { bus } from './core/bus.js';
import { appState, ChatState } from './core/state.js';
import { overlayManager } from './core/overlay.js';
import { registerActions, initActions } from './core/actions.js';
import { api } from './services/api.js';
import { healthService } from './services/health.js';

// ── Converted modules (Phase 2) ─────────────────────────────────────────────
import { LaylaUI } from './components/ui-phases.js';
import { setAspectSprite } from './components/sprites.js';
import { scrollActiveConversationIntoView } from './components/sidebar.js';
import { refreshExecutionPanels } from './components/panels.js';
import * as utils from './services/utils.js';
import * as aspect from './components/aspect.js';

// Phase 2 batch 2
import * as voice from './components/voice.js';
import * as memory from './components/memory.js';
import * as artifacts from './components/artifacts.js';
import * as autonomous from './components/autonomous.js';

// Phase 2 batch 3
import * as search from './components/search.js';
import * as planViz from './components/plan-viz.js';
import * as perf from './components/perf.js';
import * as wizard from './components/wizard.js';

// Phase 2 batch 4
import * as cluster from './components/cluster.js';
import * as growth from './components/growth.js';

// Phase 2 batch 5
import * as pairing from './components/pairing.js';
import * as setup from './components/setup.js';
import * as input from './components/input.js';

// Phase 2 batch 6
import * as bootstrap from './components/bootstrap.js';
import * as onboarding from './components/onboarding.js';

// Phase 2 batch 7
import * as settingsFull from './components/settings-full.js';
import * as conversations from './components/conversations.js';

// Phase 2 batch 8
import * as characterCreator from './components/character-creator.js';
import * as research from './components/research.js';

// Phase 2 batch 9
import * as workspace from './components/workspace.js';

// Phase 2 batch 10
import * as chatRender from './components/chat-render.js';

// GUI rebuild G2 — ⌘K command palette
import * as commandPalette from './components/command-palette.js';
// GUI rebuild P4 — System diagnostics surface
import * as systemDiagnostics from './components/system-diagnostics.js';
// GUI rebuild G5 — install self-test ("proof not a promise")
import * as selfTest from './components/self-test.js';
// GUI rebuild W-S — intent-driven Setup & Profiles wizard
import * as setupProfiles from './components/setup-profiles.js';
// W2 — German language-learning panel (headline wedge)
import * as german from './components/german.js';
// W2 — Missions board
import * as missions from './components/missions.js';
// W2 — Journal
import * as journal from './components/journal.js';
// W2 — Approvals + session grants
import * as approvals from './components/approvals.js';
// W2 — Self-improvement proposals
import * as improvements from './components/improvements.js';
// W2 — Tool-call history & health
import * as toolsHistory from './components/tools-history.js';
// W2 — Multi-device sync
import * as sync from './components/sync.js';
// W2 — Multi-aspect deliberation
import * as debate from './components/debate.js';
// W2 — Relationship codex
import * as codex from './components/codex.js';
// W2 — Verify learnings (the "it learns" loop)
import * as verify from './components/verify.js';
// W2 — Background agent tasks
import * as agentTasks from './components/agent-tasks.js';
// W2 — Knowledge base
import * as kb from './components/kb.js';
// W2 — Plans & projects
import * as plans from './components/plans.js';
// W3 — Intake quiz (REQ-80)
import * as intakeQuiz from './components/intake-quiz.js';
// W3 — Custom aspect creator (REQ-79)
import * as customAspect from './components/custom-aspect.js';
// G5 — First-run welcome (BL-091)
import * as welcome from './components/welcome.js';
// W8 — Kit marketplace (BL-156)
import * as marketplace from './components/marketplace.js';

// Phase 2 batch 11 (core orchestrator — must be last)
import * as app from './components/app.js';

// Phase 4: inline scripts converted
import * as obsidian from './components/obsidian.js';

// Models & Kits manager (persistent model control surface)
import * as models from './components/models.js';

// ── Compat bridge (exposes everything to window.* for legacy scripts) ────────
import './core/compat.js';

// ── Debug mode ───────────────────────────────────────────────────────────────
try {
  if (localStorage.getItem('layla_debug') === '1') {
    bus.setDebug(true);
    console.log('[Layla] Debug mode enabled. Bus events will be logged.');
    console.log('[Layla] Core modules loaded:', {
      bus: typeof bus,
      appState: typeof appState,
      overlayManager: typeof overlayManager,
      api: typeof api,
      healthService: typeof healthService,
    });
  }
} catch (_) {}

// ── Register known overlays ──────────────────────────────────────────────────
// These registrations map the existing DOM overlays into the managed system.
// During migration, existing show/hide code continues to work; the overlay
// manager adds proper z-index ordering and Escape handling.

function _registerOverlays() {
  overlayManager.register('setup', {
    tier: 'system',
    elementId: 'setup-overlay',
    escapable: true,
    onClose: (el) => {
      if (el) el.classList.remove('visible');
      try { if (typeof window.dismissSetupOverlay === 'function') window.dismissSetupOverlay(true); } catch (_) {}
    },
  });

  overlayManager.register('wizard', {
    tier: 'wizard',
    elementId: 'wizard-overlay',
    escapable: true,
  });

  overlayManager.register('onboarding', {
    tier: 'wizard',
    elementId: 'onboarding-overlay',
    escapable: true,
    onClose: () => {
      try { if (typeof window.dismissOnboarding === 'function') window.dismissOnboarding(); } catch (_) {}
    },
  });

  overlayManager.register('settings', {
    tier: 'modal',
    elementId: 'settings-overlay',
    escapable: true,
  });

  overlayManager.register('character-lab', {
    tier: 'modal',
    elementId: 'character-lab-overlay',
    escapable: true,
  });

  overlayManager.register('models', {
    tier: 'modal',
    elementId: 'models-overlay',
    escapable: true,
    onClose: () => { try { models.closeModelsPanel(); } catch (_) {} },
  });

  overlayManager.register('tutorial', {
    tier: 'modal',
    elementId: 'tutorial-overlay',
    escapable: true,
  });

  overlayManager.register('right-panel', {
    tier: 'panel',
    elementId: 'layla-right-panel',
    backdrop: true,
    escapable: true,
    onOpen: (el) => {
      if (el) el.classList.add('rp-open');
      const bd = document.getElementById('rp-backdrop');
      if (bd) { bd.classList.add('visible'); bd.setAttribute('aria-hidden', 'false'); }
    },
    onClose: (el) => {
      if (el) el.classList.remove('rp-open');
      const bd = document.getElementById('rp-backdrop');
      if (bd) { bd.classList.remove('visible'); bd.setAttribute('aria-hidden', 'true'); }
    },
  });

  overlayManager.register('diff-viewer', {
    tier: 'modal',
    elementId: 'diff-overlay',
    escapable: true,
  });

  overlayManager.register('keyboard-shortcuts', {
    tier: 'modal',
    elementId: 'keyboard-shortcuts-sheet',
    escapable: true,
  });

  overlayManager.register('rank-up', {
    tier: 'alert',
    elementId: 'rank-celebration-overlay',
    escapable: true,
  });
}

// ── Initialize ───────────────────────────────────────────────────────────────
function init() {
  // Register all overlays
  _registerOverlays();

  // Expose overlay convenience methods for legacy code
  window.closeRightPanel = () => overlayManager.close('right-panel');

  // Kill legacy polling loops (started by layla-app.js before this module ran)
  if (typeof window._laylaKillLegacyPolling === 'function') {
    window._laylaKillLegacyPolling();
  }

  // Start health polling service (replaces 5+ independent setInterval loops)
  healthService.start();

  // Initialize Phase 2 batch 2 modules
  voice.initVoiceControls();
  artifacts.initArtifacts();
  autonomous.initAutoMonitorHook();

  // Initialize Phase 2 batch 3 modules
  search.initSearch();
  perf.initPerf();
  wizard.initWizard();

  // Initialize Phase 2 batch 4 modules
  cluster.initCluster();

  // Initialize Phase 2 batch 6 modules
  bootstrap.initBootstrap();
  onboarding.initOnboarding();

  // Initialize Phase 2 batch 7 modules
  settingsFull.initSettings();
  conversations.initConversations();

  // Initialize Phase 2 batch 8 modules
  characterCreator.initCharacterCreator();
  research.initResearch();

  // Initialize Phase 2 batch 10 modules
  chatRender.initChatRender();

  // Initialize Phase 2 batch 11 (core orchestrator)
  app.initApp();

  // Initialize Phase 4 modules (inline scripts converted)
  obsidian.initObsidian();

  // Models & Kits manager (lazy — loads on open)
  models.initModels();

  // ── Phase 5: Register all actions for event delegation ──────────────────────
  initActions();
  registerActions({
    // aspect.js
    setAspect: (id) => { aspect.setAspect(id); aspect.toggleAspectDescription(id); },
    toggleAspectLock: aspect.toggleAspectLock,
    refreshMaturityCard: () => aspect.refreshMaturityCard(true),
    // input.js
    toggleTheme: input.toggleTheme,
    toggleSidebarCompact: input.toggleSidebarCompact,
    toggleMobileSidebar: input.toggleMobileSidebar,
    closeMobileSidebar: input.closeMobileSidebar,
    toggleRightPanel: input.toggleRightPanel,
    closeRightPanel: input.closeRightPanel,
    openOverlayPanel: input.openOverlayPanel,
    exportChat: input.exportChat,
    clearChat: input.clearChat,
    fillPrompt: input.fillPrompt,
    openCliHelp: input.openCliHelp,
    attachFile: input.attachFile,
    dismissUrlChip: input.dismissUrlChip,
    acceptUrlFetch: input.acceptUrlFetch,
    handleFileDrop: input.handleFileDrop,
    showPanelTab: input.showPanelTab,
    focusResearchPanel: input.focusResearchPanel,
    openChatSearch: input.openChatSearch,
    closeChatSearch: input.closeChatSearch,
    chatSearchNext: input.chatSearchNext,
    onChatSearchInput: input.onChatSearchInput,
    closeDiffViewer: input.closeDiffViewer,
    confirmApplyFile: input.confirmApplyFile,
    closeBatchDiffViewer: input.closeBatchDiffViewer,
    confirmApplyBatch: input.confirmApplyBatch,
    onInputKeydown: input.onInputKeydown,
    onInputChange: (_val, e) => { input.onInputChange(e); },
    // bootstrap.js
    toggleHeaderOverflow: bootstrap.toggleHeaderOverflow,
    showMainPanel: bootstrap.showMainPanel,
    showWorkspaceSubtab: bootstrap.showWorkspaceSubtab,
    showKeyboardShortcutsSheet: bootstrap.showKeyboardShortcutsSheet,
    hideKeyboardShortcutsSheet: bootstrap.hideKeyboardShortcutsSheet,
    triggerSend: bootstrap.triggerSend,
    // conversations.js
    startNewConversation: conversations.startNewConversation,
    toggleChatRailMobile: conversations.toggleChatRailMobile,
    closeChatRailMobile: conversations.closeChatRailMobile,
    createProjectQuick: conversations.createProjectQuick,
    onProjectSelectChange: conversations.onProjectSelectChange,
    // settings-full.js
    openSettings: settingsFull.openSettings,
    closeSettings: settingsFull.closeSettings,
    saveSettings: settingsFull.saveSettings,
    applySettingsPreset: settingsFull.applySettingsPreset,
    saveAppearanceLite: settingsFull.saveAppearanceLite,
    checkForUpdates: settingsFull.checkForUpdates,
    saveContentPolicySettings: settingsFull.saveContentPolicySettings,
    setDeliberationMode: settingsFull.setDeliberationMode,
    addWorkspacePreset: settingsFull.addWorkspacePreset,
    removeWorkspacePreset: settingsFull.removeWorkspacePreset,
    onWorkspacePresetSelect: settingsFull.onWorkspacePresetSelect,
    refreshRelationshipCodex: settingsFull.refreshRelationshipCodex,
    saveRelationshipCodex: settingsFull.saveRelationshipCodex,
    runKnowledgeIngest: settingsFull.runKnowledgeIngest,
    laylaGitUndoCheckpoint: settingsFull.laylaGitUndoCheckpoint,
    laylaLoadOptionalFeatures: settingsFull.laylaLoadOptionalFeatures,
    laylaImportChat: settingsFull.laylaImportChat,
    // chat-render.js
    toggleComposePanel: chatRender.toggleComposePanel,
    retryLastMessage: chatRender.retryLastMessage,
    toggleSendButton: chatRender.toggleSendButton,
    // app.js
    compactConversation: app.compactConversation,
    cancelActiveSend: app.cancelActiveSend,
    // setup.js
    startModelDownload: setup.startModelDownload,
    retryModelDownload: setup.retryModelDownload,
    dismissSetupOverlay: setup.dismissSetupOverlay,
    // character-creator.js
    openCharacterLab: characterCreator.openCharacterLab,
    closeCharacterLab: characterCreator.closeCharacterLab,
    // voice.js
    toggleMic: voice.toggleMic,
    // search.js
    laylaGlobalSearchInput: search.laylaGlobalSearchInput,
    laylaGlobalSearchKey: search.laylaGlobalSearchKey,
    laylaGlobalSearchClose: search.laylaGlobalSearchClose,
    // workspace.js
    laylaRefreshWorkspaceAwareness: workspace.laylaRefreshWorkspaceAwareness,
    laylaLoadProjectMemoryInspector: workspace.laylaLoadProjectMemoryInspector,
    laylaWorkspaceSymbolSearch: workspace.laylaWorkspaceSymbolSearch,
    studyTopicFromChatInput: workspace.studyTopicFromChatInput,
    studyTopicFromLastUserMessage: workspace.studyTopicFromLastUserMessage,
    addStudyPlan: workspace.addStudyPlan,
    deleteStudyPlan: workspace.deleteStudyPlan,
    refreshLaylaPlansPanel: workspace.refreshLaylaPlansPanel,
    refreshFileCheckpointsPanel: workspace.refreshFileCheckpointsPanel,
    refreshSkillsList: workspace.refreshSkillsList,
    refreshAgentsPanel: workspace.refreshAgentsPanel,
    wsRefreshExecutionPanels: workspace.wsRefreshExecutionPanels,
    onMemorySearch: workspace.onMemorySearch,
    runElasticsearchLearningSearch: workspace.runElasticsearchLearningSearch,
    laylaRunSetupAuto: workspace.laylaRunSetupAuto,
    laylaRunDoctor: workspace.laylaRunDoctor,
    // memory.js
    showMemorySubTab: memory.showMemorySubTab,
    laylaMemBrowse: memory.laylaMemBrowse,
    laylaImportMemoryBundle: memory.laylaImportMemoryBundle,
    // artifacts.js
    laylaArtifactsScan: artifacts.laylaArtifactsScan,
    laylaArtifactsClear: artifacts.laylaArtifactsClear,
    laylaArtifactEditClose: artifacts.laylaArtifactEditClose,
    laylaArtifactCopyEdit: artifacts.laylaArtifactCopyEdit,
    laylaArtifactSendEdit: artifacts.laylaArtifactSendEdit,
    // autonomous.js
    laylaAutoStop: autonomous.laylaAutoStop,
    laylaAutoMonitorClose: autonomous.laylaAutoMonitorClose,
    // research.js
    sendResearch: research.sendResearch,
    startResearchMission: research.startResearchMission,
    refreshMissionStatus: research.refreshMissionStatus,
    showResearchTab: research.showResearchTab,
    laylaRunInvestigation: research.laylaRunInvestigation,
    laylaInvestigationTemplateTrace: research.laylaInvestigationTemplateTrace,
    laylaInvestigationTemplateStructure: research.laylaInvestigationTemplateStructure,
    laylaInvestigationTemplateBug: research.laylaInvestigationTemplateBug,
    laylaRunAutonomousResearch: research.laylaRunAutonomousResearch,
    // growth.js
    refreshGrowthDashboard: growth.refreshGrowthDashboard,
    laylaVerifyReviewOpen: growth.laylaVerifyReviewOpen,
    laylaVerifyReviewClose: growth.laylaVerifyReviewClose,
    laylaVerifyConfirm: growth.laylaVerifyConfirm,
    laylaVerifyReject: growth.laylaVerifyReject,
    // cluster.js
    refreshClusterStatus: cluster.refreshClusterStatus,
    generatePairingToken: cluster.generatePairingToken,
    toggleClusterEnabled: cluster.toggleClusterEnabled,
    pairAsDrone: cluster.pairAsDrone,
    // pairing.js
    startDiscovery: pairing.startDiscovery,
    stopDiscovery: pairing.stopDiscovery,
    refreshPeeringPanel: pairing.refreshPeeringPanel,
    // plan-viz.js
    laylaCloseViz: planViz.laylaCloseViz,
    // perf.js
    laylaVoiceSpeedChange: perf.laylaVoiceSpeedChange,
    laylaVoiceVolumeChange: perf.laylaVoiceVolumeChange,
    laylaVoicePreview: perf.laylaVoicePreview,
    // obsidian.js
    laylaObsidianConnect: obsidian.laylaObsidianConnect,
    laylaObsidianSync: obsidian.laylaObsidianSync,
    laylaObsidianStatus: obsidian.laylaObsidianStatus,
    laylaObsidianDiff: obsidian.laylaObsidianDiff,
    laylaObsidianSuggest: obsidian.laylaObsidianSuggest,
    // models.js
    openModelsPanel: models.openModelsPanel,
    closeModelsPanel: models.closeModelsPanel,
    refreshModelsPanel: models.refreshModelsPanel,
    switchActiveModel: models.switchActiveModel,
    downloadCatalogModel: models.downloadCatalogModel,
    // ── Compound/wrapper actions for HTML handler conversion ──
    clearGlobalSearch: () => {
      var el = document.getElementById('global-search-input');
      if (el) el.value = '';
      search.laylaGlobalSearchClose();
    },
    showWorkspaceKnowledge: () => {
      bootstrap.showMainPanel('workspace');
      bootstrap.showWorkspaceSubtab('knowledge');
    },
    toggleDiscovery: () => {
      if (window._discoveryRunning) pairing.stopDiscovery();
      else pairing.startDiscovery();
    },
    refreshMissionAndTab: () => {
      research.refreshMissionStatus().then(function () {
        var t = document.querySelector('#research-mission-panel .tab-btn.active');
        if (t) research.showResearchTab(t.getAttribute('data-tab'));
      });
    },
    laylaMemBrowseReset: () => { memory.laylaMemBrowse(0); },
    toggleTts: (checked) => {
      window._ttsEnabled = checked;
      localStorage.setItem('layla_tts', checked);
      var t1 = document.getElementById('tts-toggle');
      var t2 = document.getElementById('tts-toggle2');
      if (t1) t1.checked = checked;
      if (t2) t2.checked = checked;
    },
    savePipelineMode: (val) => {
      try { localStorage.setItem('layla_engineering_pipeline_mode', val); } catch (_) {}
    },
    syncModelOverride: (val) => {
      var el = document.getElementById('model-override');
      if (el) el.value = val;
    },
    saveArtifactsAutoscan: (checked) => {
      localStorage.setItem('layla_artifacts_autoscan', checked);
    },
    saveIdbCache: (checked) => {
      localStorage.setItem('layla_idb_cache', checked);
    },
    toggleLowFx: (checked) => {
      document.documentElement.style.setProperty('--fx-strength', checked ? '0.4' : '1.5');
      localStorage.setItem('layla_low_fx', checked);
    },
    dismissPipelineClarify: () => {
      var el = document.getElementById('pipeline-clarify-panel');
      if (el) el.style.display = 'none';
    },
    saveComposeDraft: (val) => {
      try { localStorage.setItem('layla_compose_draft', val); } catch (_) {}
    },
    attachFileChange: (e) => {
      if (e && e.target) input.attachFile(e.target);
    },
  });

  // ── GUI rebuild G2 · ⌘K command palette ────────────────────────────────────
  // The aspects ARE the navigation (design principle 4): the palette makes
  // switching persona + jumping to a screen the fastest gesture in the app.
  // BL-122: derive from the single canonical roster (aspect.ASPECTS) — no duplicate
  // list here, so adding/renaming an aspect only touches components/aspect.js.
  const paletteCommands = [
    ...aspect.ASPECTS.map((a) => ({
      id: 'asp-' + a.id, group: 'Aspect', label: 'Switch to ' + a.name,
      keywords: ['persona', 'aspect', a.id],
      run: () => { aspect.setAspect(a.id); aspect.toggleAspectDescription(a.id); },
    })),
    { id: 'go-settings', group: 'Go to', label: 'Settings', keywords: ['config', 'preferences'], run: () => settingsFull.openSettings() },
    { id: 'go-lab', group: 'Go to', label: 'Character Lab', keywords: ['aspect', 'create', 'persona', 'edit'], run: () => characterCreator.openCharacterLab() },
    { id: 'go-models', group: 'Go to', label: 'Models & Kits', keywords: ['model', 'gguf', 'kit'], run: () => models.openModelsPanel() },
    { id: 'go-dashboard', group: 'Go to', label: 'Dashboard', keywords: ['status', 'health', 'system'], run: () => bootstrap.showMainPanel('status') },
    { id: 'go-library', group: 'Go to', label: 'Library', keywords: ['workspace', 'memory', 'knowledge', 'files'], run: () => bootstrap.showMainPanel('workspace') },
    { id: 'go-research', group: 'Go to', label: 'Research', keywords: ['investigate', 'mission'], run: () => bootstrap.showMainPanel('research') },
    { id: 'go-artifacts', group: 'Go to', label: 'Artifacts', keywords: ['files', 'output'], run: () => bootstrap.showMainPanel('artifacts') },
    { id: 'chat-new', group: 'Chat', label: 'New conversation', keywords: ['start', 'fresh'], run: () => conversations.startNewConversation() },
    { id: 'chat-clear', group: 'Chat', label: 'Clear chat', keywords: ['reset'], run: () => input.clearChat() },
    { id: 'chat-export', group: 'Chat', label: 'Export chat', keywords: ['save', 'download', 'markdown'], run: () => input.exportChat() },
    { id: 'chat-retry', group: 'Chat', label: 'Retry last message', keywords: ['regenerate'], run: () => chatRender.retryLastMessage() },
    { id: 'view-theme', group: 'View', label: 'Toggle theme', keywords: ['dark', 'light'], run: () => input.toggleTheme() },
    { id: 'view-panel', group: 'View', label: 'Toggle context panel', keywords: ['right', 'sidebar'], run: () => input.toggleRightPanel() },
    { id: 'view-shortcuts', group: 'View', label: 'Keyboard shortcuts', keywords: ['help', 'keys'], run: () => bootstrap.showKeyboardShortcutsSheet() },
    { id: 'sys-diagnostics', group: 'Go to', label: 'System diagnostics', keywords: ['metrics', 'cot', 'audit', 'capabilities', 'health', 'cost'], run: () => systemDiagnostics.openSystemDiagnostics() },
    { id: 'self-test', group: 'Go to', label: 'Run self-test', keywords: ['proof', 'health', 'verify', 'diagnose', 'works', 'model'], run: () => selfTest.openSelfTest() },
    { id: 'setup-wizard', group: 'Go to', label: 'Set up / reconfigure Layla', keywords: ['setup', 'onboarding', 'profile', 'features', 'install', 'enable', 'reconfigure'], run: () => setupProfiles.openSetupProfiles() },
    { id: 'german', group: 'Go to', label: 'German (learn / check / flashcards)', keywords: ['deutsch', 'language', 'learning', 'correct', 'flashcards', 'cefr'], run: () => german.openGerman() },
    { id: 'missions', group: 'Go to', label: 'Missions board', keywords: ['mission', 'board', 'tasks', 'long', 'autonomous', 'kanban'], run: () => missions.openMissions() },
    { id: 'journal', group: 'Go to', label: 'Journal', keywords: ['journal', 'diary', 'reflection', 'notes', 'entries'], run: () => journal.openJournal() },
    { id: 'approvals', group: 'Go to', label: 'Approvals & grants', keywords: ['approval', 'pending', 'grant', 'permission', 'security', 'approve', 'deny'], run: () => approvals.openApprovals() },
    { id: 'improvements', group: 'Go to', label: 'Improvements (self)', keywords: ['improve', 'proposal', 'self', 'growth', 'suggestion', 'approve'], run: () => improvements.openImprovements() },
    { id: 'tools-history', group: 'Go to', label: 'Tool history & health', keywords: ['tools', 'history', 'analysis', 'health', 'success', 'latency', 'debug'], run: () => toolsHistory.openToolsHistory() },
    { id: 'sync', group: 'Go to', label: 'Sync (devices)', keywords: ['sync', 'syncthing', 'devices', 'multi', 'phone', 'pair'], feature: 'remote', run: () => sync.openSync() },
    { id: 'debate', group: 'Go to', label: 'Deliberate (aspects)', keywords: ['debate', 'deliberate', 'council', 'tribunal', 'aspects', 'decide'], feature: 'multi_agent', run: () => debate.openDebate() },
    { id: 'codex', group: 'Go to', label: 'Relationship codex', keywords: ['codex', 'relationship', 'entities', 'people', 'who', 'knows'], run: () => codex.openCodex() },
    { id: 'verify', group: 'Go to', label: 'Verify learnings', keywords: ['verify', 'learn', 'confirm', 'correct', 'facts', 'memory'], run: () => verify.openVerify() },
    { id: 'agent-tasks', group: 'Go to', label: 'Background tasks', keywords: ['background', 'tasks', 'agent', 'queue', 'running', 'async'], run: () => agentTasks.openAgentTasks() },
    { id: 'kb', group: 'Go to', label: 'Knowledge base', keywords: ['knowledge', 'kb', 'articles', 'wiki', 'notes', 'reference', 'build'], run: () => kb.openKb() },
    { id: 'plans', group: 'Go to', label: 'Plans & projects', keywords: ['plans', 'projects', 'goal', 'steps', 'approve', 'execute', 'planner', 'roadmap'], run: () => plans.openPlans() },
    { id: 'intake-quiz', group: 'Go to', label: 'Intake quiz', keywords: ['quiz', 'intake', 'special', 'profile', 'stats', 'onboarding', 'personality'], run: () => intakeQuiz.openIntakeQuiz() },
    { id: 'custom-aspect', group: 'Go to', label: 'Create custom aspect', keywords: ['aspect', 'create', 'custom', 'persona', 'new', 'sigil', 'character'], run: () => customAspect.openCustomAspect() },
    { id: 'welcome', group: 'Go to', label: 'Welcome / about Layla', keywords: ['welcome', 'about', 'intro', 'onboarding', 'values', 'honesty', 'start'], run: () => welcome.openWelcome() },
    { id: 'marketplace', group: 'Go to', label: 'Kit marketplace', keywords: ['kit', 'marketplace', 'install', 'features', 'bundle', 'store', 'capabilities'], run: () => marketplace.openMarketplace() },
  ];
  commandPalette.initCommandPalette(paletteCommands);
  window.openCommandPalette = commandPalette.openCommandPalette;
  // Expose the profile wizard + welcome so the first-run sequence (setup.js) can present them.
  window.openSetupProfiles = setupProfiles.openSetupProfiles;
  window.openWelcome = welcome.openWelcome;
  window.maybeShowWelcome = welcome.maybeShowWelcome;
  // BL-208: gate feature-tagged palette commands by which optional features are enabled.
  // Fail-open (show all) until this resolves; refresh whenever the setup wizard applies.
  const _refreshEnabledFeatures = () => {
    fetch('/setup/state', { headers: { Accept: 'application/json' } })
      .then((r) => r.json())
      .then((d) => { if (d && Array.isArray(d.enabled_features)) commandPalette.setEnabledFeatures(d.enabled_features); })
      .catch(() => {});
  };
  _refreshEnabledFeatures();
  window.addEventListener('layla:profiles-applied', _refreshEnabledFeatures);
  registerActions({
    openCommandPalette: commandPalette.openCommandPalette,
    closeCommandPalette: commandPalette.closeCommandPalette,
    openSystemDiagnostics: systemDiagnostics.openSystemDiagnostics,
    closeSystemDiagnostics: systemDiagnostics.closeSystemDiagnostics,
    openSelfTest: selfTest.openSelfTest,
    runSelfTest: selfTest.runSelfTest,
    openSetupProfiles: setupProfiles.openSetupProfiles,
    closeSetupProfiles: setupProfiles.closeSetupProfiles,
    openGerman: german.openGerman,
    closeGerman: german.closeGerman,
    openMissions: missions.openMissions,
    closeMissions: missions.closeMissions,
    openJournal: journal.openJournal,
    closeJournal: journal.closeJournal,
    openApprovals: approvals.openApprovals,
    closeApprovals: approvals.closeApprovals,
    openImprovements: improvements.openImprovements,
    closeImprovements: improvements.closeImprovements,
    openToolsHistory: toolsHistory.openToolsHistory,
    closeToolsHistory: toolsHistory.closeToolsHistory,
    openSync: sync.openSync,
    closeSync: sync.closeSync,
    openDebate: debate.openDebate,
    closeDebate: debate.closeDebate,
    openCodex: codex.openCodex,
    closeCodex: codex.closeCodex,
    openVerify: verify.openVerify,
    closeVerify: verify.closeVerify,
    openAgentTasks: agentTasks.openAgentTasks,
    closeAgentTasks: agentTasks.closeAgentTasks,
    openKb: kb.openKb,
    closeKb: kb.closeKb,
    openPlans: plans.openPlans,
    closePlans: plans.closePlans,
    openIntakeQuiz: intakeQuiz.openIntakeQuiz,
    closeIntakeQuiz: intakeQuiz.closeIntakeQuiz,
    openCustomAspect: customAspect.openCustomAspect,
    closeCustomAspect: customAspect.closeCustomAspect,
    openWelcome: welcome.openWelcome,
    closeWelcome: welcome.closeWelcome,
    openMarketplace: marketplace.openMarketplace,
    closeMarketplace: marketplace.closeMarketplace,
  });

  // Apply timeout config from health response
  bus.on('health:deep-update', (d) => {
    try {
      if (typeof window.laylaApplyUiTimeoutsFromHealth === 'function') {
        window.laylaApplyUiTimeoutsFromHealth(d);
      }
    } catch (_) {}
  });

  // Profile default aspect auto-switch (Phase 4B from bootstrap.js)
  bus.on('profile:default-aspect', (aspect) => {
    if (!window._aspectManuallySet && typeof window.setAspect === 'function') {
      window.setAspect(aspect);
    }
  });

  console.log('[Layla] main.js initialized — ES module system active');
  bus.emit('app:initialized');
}

// ── Run init when DOM is ready ───────────────────────────────────────────────
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  // DOM already ready (module scripts are deferred by default)
  init();
}

// ── Exports for future module consumers ──────────────────────────────────────
export { bus, appState, ChatState, overlayManager, api, healthService };

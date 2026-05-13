/**
 * layla-setup.js — First-run setup overlay and onboarding wizard.
 * Depends on: layla-utils.js, layla-aspect.js (highlightAspectSidebar)
 */
(function () {
  'use strict';

  var _setupSelectedModel = null;
  var _setupEventSource = null;

  function stopModelDownloadStream() {
    try {
      if (_setupEventSource) {
        _setupEventSource.close();
        _setupEventSource = null;
      }
    } catch (_) {}
  }

  function _setupRefreshDownloadButton() {
    var btn = document.getElementById('setup-download-btn');
    if (!btn) return;
    var customEl = document.getElementById('setup-custom-url');
    var custom = (customEl && customEl.value || '').trim();
    btn.disabled = !((_setupSelectedModel && _setupSelectedModel.url) || custom);
  }

  async function saveSetupWorkspaceIfNeeded() {
    var inp = document.getElementById('setup-workspace-path');
    var path = (inp && inp.value || '').trim();
    if (!path) return;
    try {
      await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sandbox_root: path }),
      });
    } catch (_) {}
  }

  function renderSetupHardware(hw) {
    var el = document.getElementById('setup-hw');
    if (!el) return;
    if (!hw || !Object.keys(hw).length) {
      el.textContent = 'Hardware details unavailable — you can tune the model in Settings after setup.';
      return;
    }
    var lines = [];
    if (hw.ram_gb != null) lines.push('RAM: ~' + hw.ram_gb + ' GB');
    if (hw.gpu_vendor && hw.gpu_vendor !== 'none') {
      lines.push('GPU: ' + hw.gpu_vendor + (hw.vram_gb != null ? ' (~' + hw.vram_gb + ' GB VRAM)' : ''));
    } else lines.push('GPU: not detected (CPU inference)');
    if (hw.suggestion) lines.push('Hint: ' + hw.suggestion);
    el.innerHTML = lines.map(function (l) { return escapeHtml(l); }).join('<br>');
  }

  function renderSetupExistingModels(list) {
    var wrap = document.getElementById('setup-existing-models');
    var lst = document.getElementById('setup-existing-list');
    if (!wrap || !lst) return;
    if (!list || !list.length) {
      wrap.style.display = 'none';
      return;
    }
    wrap.style.display = 'block';
    lst.innerHTML = list.map(function (name) {
      return '<button type="button" class="tab-btn setup-model-pick" style="margin:4px 4px 4px 0" data-filename="' + String(name).replace(/"/g, '&quot;') + '">Use ' + escapeHtml(String(name)) + '</button>';
    }).join(' ');
    lst.querySelectorAll('.setup-model-pick').forEach(function (btn) {
      btn.onclick = function () { useExistingSetupModel(btn.getAttribute('data-filename')); };
    });
  }

  async function useExistingSetupModel(filename) {
    await saveSetupWorkspaceIfNeeded();
    stopModelDownloadStream();
    try {
      var res = await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_filename: filename }),
      });
      if (res.ok) {
        var o = document.getElementById('setup-overlay');
        if (o) o.classList.remove('visible');
        showToast('Model selected');
        await checkSetupStatus();
      } else showToast('Could not save model setting');
    } catch (_) {
      showToast('Save failed');
    }
  }

  function _renderSetupCatalogError(container, message) {
    if (!container) return;
    var msg = message || 'Could not load catalog';
    container.innerHTML =
      '<div style="color:var(--text-dim);font-size:0.8rem;line-height:1.45">' + escapeHtml(msg) + '</div>' +
      '<button type="button" class="tab-btn" style="margin-top:10px" onclick="loadSetupCatalog()">Retry</button>';
  }

  async function loadSetupCatalog() {
    var container = document.getElementById('setup-model-list');
    if (!container) return;
    container.innerHTML = '<div style="color:var(--text-dim);font-size:0.8rem">Loading catalog…</div>';
    try {
      var res = await fetchWithTimeout('/setup/models', {}, 20000);
      var data = await res.json().catch(function () { return null; });
      if (!res.ok || !data || !data.ok || !Array.isArray(data.catalog)) {
        _renderSetupCatalogError(container, (data && data.error) || formatAgentError(res, data || {}));
        return;
      }
      container.innerHTML = '';
      data.catalog.forEach(function (m) {
        var div = document.createElement('div');
        div.className = 'setup-catalog-row';
        div.setAttribute('data-match-name', String(m.name || '').toLowerCase());
        div.setAttribute('data-match-key', String(m.key || '').toLowerCase());
        div.setAttribute('data-match-file', String(m.filename || m.gguf_filename || '').toLowerCase());
        div.style.cssText = 'margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;cursor:pointer;opacity:' + (m.viable ? '1' : '0.55');
        div.innerHTML = '<strong>' + escapeHtml(m.name || '') + '</strong> <span style="font-size:0.7rem;color:var(--text-dim)">' + (m.recommended ? '(recommended) ' : '') + (m.viable ? '' : ' — may need more RAM') + '</span><br><span style="font-size:0.72rem;color:var(--text-dim)">' + escapeHtml(m.desc || '') + '</span>';
        div.onclick = function () {
          if (!m.viable && !confirm('This model may exceed your detected RAM. Download anyway?')) return;
          _setupSelectedModel = m;
          container.querySelectorAll('.setup-catalog-row').forEach(function (el) { el.style.outline = ''; });
          div.style.outline = '2px solid var(--asp)';
          _setupRefreshDownloadButton();
        };
        container.appendChild(div);
      });
      _setupRefreshDownloadButton();
    } catch (e) {
      var timedOut = e && e.name === 'AbortError';
      _renderSetupCatalogError(container, timedOut ? 'Catalog request timed out.' : 'Failed to load catalog');
    }
  }
  window.loadSetupCatalog = loadSetupCatalog;

  async function prefillSetupWorkspaceFromSettings(statusPayload) {
    var inp = document.getElementById('setup-workspace-path');
    if (!inp || inp.getAttribute('data-user-edited') === '1') return;
    var sr = '';
    if (statusPayload && (statusPayload.sandbox_root || '').trim()) {
      sr = String(statusPayload.sandbox_root || '').trim();
    }
    if (!sr) {
      try {
        var r = await fetch('/settings');
        if (r.ok) {
          var cfg = await r.json();
          sr = (cfg.sandbox_root || '').trim();
        }
      } catch (_) {}
    }
    if (sr && !inp.value) inp.value = sr;
  }

  function trySelectSetupCatalogMatch(statusPayload) {
    if (!statusPayload) return;
    var want = String(statusPayload.resolved_model || statusPayload.model_filename || '').trim().toLowerCase();
    if (!want) return;
    var container = document.getElementById('setup-model-list');
    if (!container) return;
    var rows = container.querySelectorAll('.setup-catalog-row');
    rows.forEach(function (div) {
      var fn = String(div.getAttribute('data-match-file') || '').toLowerCase();
      var nm = String(div.getAttribute('data-match-name') || '').toLowerCase();
      var key = String(div.getAttribute('data-match-key') || '').toLowerCase();
      if (!want) return;
      if (fn === want || fn.indexOf(want) >= 0 || want.indexOf(fn) >= 0 || nm.indexOf(want) >= 0 || key === want) {
        div.click();
      }
    });
  }

  function _renderSetupStatusError(res, body, err) {
    var overlay = document.getElementById('setup-overlay');
    if (overlay) overlay.classList.add('visible');
    var el = document.getElementById('setup-hw');
    if (!el) return;
    var msg =
      err && err.name === 'AbortError'
        ? 'Setup status timed out. Check that Layla is responding.'
        : res
          ? formatAgentError(res, body || {})
          : 'Could not reach Layla. Is the server running?';
    el.innerHTML =
      '<span style="color:var(--text-dim)">' + escapeHtml(msg) + '</span><br>' +
      '<button type="button" class="tab-btn" style="margin-top:8px" onclick="checkSetupStatus()">Retry</button>';
  }

  async function checkSetupStatus() {
    var overlay = document.getElementById('setup-overlay');
    try {
      var res = await fetchWithTimeout('/setup_status', {}, 15000);
      var s = await res.json().catch(function () { return null; });
      if (!res.ok || !s) {
        _renderSetupStatusError(res, s, null);
        return;
      }
      if (s.ready && s.model_found) {
        if (overlay) overlay.classList.remove('visible');
        maybeStartOnboarding();
        return;
      }
      if (overlay) overlay.classList.add('visible');
      await prefillSetupWorkspaceFromSettings(s);
      renderSetupHardware(s.hardware || {});
      renderSetupExistingModels(s.available_models || []);
      await loadSetupCatalog();
      trySelectSetupCatalogMatch(s);
      _setupRefreshDownloadButton();
    } catch (e) {
      if (typeof _dbg === 'function') _dbg('checkSetupStatus failed', e);
      _renderSetupStatusError(null, null, e);
      if (typeof showToast === 'function') showToast('Setup check failed — is Layla running?');
    }
  }
  window.checkSetupStatus = checkSetupStatus;

  // ── Model download ─────────────────────────────────────────────────────────
  function startModelDownload() {
    var url = '';
    var filename = '';
    if (_setupSelectedModel && _setupSelectedModel.url) {
      url = _setupSelectedModel.url;
      filename = _setupSelectedModel.filename || '';
    } else {
      var customEl = document.getElementById('setup-custom-url');
      url = (customEl && customEl.value || '').trim();
    }
    if (!url) {
      showToast('Select a model or paste a .gguf URL');
      return;
    }
    stopModelDownloadStream();
    var bar = document.getElementById('setup-progress-bar');
    var label = document.getElementById('setup-progress-label');
    var doneMsg = document.getElementById('setup-done-msg');
    var retryBtn = document.getElementById('setup-retry-btn');
    if (bar) bar.style.width = '0%';
    if (label) label.textContent = 'Starting download…';
    if (doneMsg) doneMsg.textContent = '';
    if (retryBtn) retryBtn.style.display = 'none';

    saveSetupWorkspaceIfNeeded().then(function () {
      var qs = '/setup/download?url=' + encodeURIComponent(url);
      if (filename) qs += '&filename=' + encodeURIComponent(filename);
      try {
        _setupEventSource = new EventSource(qs);
      } catch (err) {
        showToast('Download could not start');
        return;
      }
      _setupEventSource.onmessage = function (ev) {
        try {
          var d = JSON.parse(ev.data);
          if (d.error) {
            stopModelDownloadStream();
            if (label) label.textContent = 'Error: ' + d.error;
            if (retryBtn) retryBtn.style.display = '';
            showToast('Download failed');
            return;
          }
          if (typeof d.pct === 'number' && bar) bar.style.width = d.pct + '%';
          if (label && typeof d.dl_mb === 'number' && typeof d.tot_mb === 'number') {
            label.textContent = 'Downloading… ' + d.pct + '% (' + d.dl_mb + ' / ' + d.tot_mb + ' MB)';
          } else if (label) label.textContent = 'Downloading…';
          if (d.done) {
            stopModelDownloadStream();
            if (doneMsg) doneMsg.textContent = 'Done — ' + (d.filename || 'model saved');
            showToast('Model ready');
            setTimeout(function () {
              var o = document.getElementById('setup-overlay');
              if (o) o.classList.remove('visible');
              checkSetupStatus();
            }, 400);
          }
        } catch (_) {}
      };
      _setupEventSource.onerror = function () {
        stopModelDownloadStream();
        if (label) label.textContent = 'Connection lost — try Retry';
        if (retryBtn) retryBtn.style.display = '';
      };
    });
  }
  window.startModelDownload = startModelDownload;

  function retryModelDownload() {
    var retryBtn = document.getElementById('setup-retry-btn');
    if (retryBtn) retryBtn.style.display = 'none';
    startModelDownload();
  }
  window.retryModelDownload = retryModelDownload;

  function dismissSetupOverlay(isSkip) {
    var o = document.getElementById('setup-overlay');
    if (o) o.classList.remove('visible');
    if (isSkip === true) saveSetupWorkspaceIfNeeded();
    maybeStartOnboarding();
  }
  window.dismissSetupOverlay = dismissSetupOverlay;

  // ── Onboarding ─────────────────────────────────────────────────────────────
  var _onboardingStep = 0;

  function renderOnboardingStep() {
    var text = document.getElementById('onboarding-text');
    var nextBtn = document.getElementById('onboarding-next');
    var doneBtn = document.getElementById('onboarding-done');
    if (!text) return;
    if (typeof highlightAspectSidebar === 'function') highlightAspectSidebar(false);
    if (_onboardingStep <= 0) {
      text.textContent = 'Layla only reads and writes inside your workspace folder (set in First Setup or Prefs). File changes and shell commands stay behind approval gates.';
      if (doneBtn) doneBtn.style.display = 'none';
      if (nextBtn) nextBtn.style.display = '';
      return;
    }
    if (_onboardingStep === 1) {
      text.textContent = 'Pick a voice (facet) in the sidebar — Morrigan for engineering, Nyx for research, Echo for continuity, and more.';
      if (typeof highlightAspectSidebar === 'function') highlightAspectSidebar(true);
      if (doneBtn) doneBtn.style.display = 'none';
      if (nextBtn) nextBtn.style.display = '';
      return;
    }
    text.textContent = 'Use the padlock next to the aspect badge to lock routing. You can revisit VALUES.md and ethics from Help anytime.';
    if (nextBtn) nextBtn.style.display = 'none';
    if (doneBtn) doneBtn.style.display = '';
  }

  function maybeStartOnboarding() {
    try {
      if (localStorage.getItem('layla_onboarding_v1_done') === '1') return;
      var ov = document.getElementById('onboarding-overlay');
      if (!ov) return;
      _onboardingStep = 0;
      renderOnboardingStep();
      ov.classList.add('visible');
    } catch (_) {}
  }

  function onboardingNext() {
    _onboardingStep++;
    if (_onboardingStep > 2) _onboardingStep = 2;
    renderOnboardingStep();
  }
  window.onboardingNext = onboardingNext;

  function dismissOnboarding() {
    var ov = document.getElementById('onboarding-overlay');
    if (ov) ov.classList.remove('visible');
    try { localStorage.setItem('layla_onboarding_v1_done', '1'); } catch (_) {}
    if (typeof highlightAspectSidebar === 'function') highlightAspectSidebar(false);
  }
  window.dismissOnboarding = dismissOnboarding;

  // Expose internal for DOMContentLoaded wiring
  window._setupRefreshDownloadButton = _setupRefreshDownloadButton;

  window.laylaSetupModuleLoaded = true;
})();

/**
 * components/voice.js — Voice recording, TTS playback, and audio controls.
 *
 * Converted from js/layla-voice.js (IIFE -> ES module).
 * Depends on: services/utils.js (showToast), components/aspect.js (ASPECT_COLORS),
 *             components/sprites.js (setAspectSprite), core/state.js (appState)
 */

import { bus } from '../core/bus.js';
import { appState } from '../core/state.js';
import { cleanLaylaText, showToast } from '../services/utils.js';

// ── Per-aspect TTS voice styles (browser SpeechSynthesis fallback) ──────────
export const TTS_VOICE_STYLES = {
  morrigan:  { rate: 1.05, pitch: 0.90 },
  nyx:       { rate: 0.82, pitch: 0.88 },
  eris:      { rate: 1.20, pitch: 1.12 },
  echo:      { rate: 0.90, pitch: 1.10 },
  cassandra: { rate: 1.15, pitch: 1.05 },
  lilith:    { rate: 0.78, pitch: 0.88 },
};

// Project markdown → plain text for SpeechSynthesis (mirrors the server's _text_for_speech). The
// reply cleaners deliberately PRESERVE markdown for marked.parse, so without this the browser TTS
// fallback reads "##", "**", backticks and table pipes aloud as noise.
function _speechText(t) {
  if (!t) return '';
  // Strip a leading persona/speaker label first (name-gated, incl. reasoning traces) so the browser TTS
  // fallback never speaks "Morrigan:" / "Morrigan [The Blade]:" if handed raw reply text — parity with
  // the server /voice/speak path. Then project the remaining markdown to plain speech.
  try { t = cleanLaylaText(String(t)); } catch (_e) { t = String(t); }
  return String(t)
    .replace(/<\/?[A-Za-z][^>]*>/g, ' ')              // model-emitted inline HTML tags (parity w/ server _text_for_speech)
    .replace(/```[^\n]*\n[\s\S]*?(?:```|$)/g, ' ')   // fenced code blocks
    .replace(/`([^`]*)`/g, '$1')                       // inline code
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')           // [label](url) → label
    .replace(/[*_~]{1,3}/g, '')                        // bold/italic/strike markers
    .replace(/^\s{0,3}#{1,6}[ \t]*/gm, '')             // heading hashes
    .replace(/^\s*>[ \t]?/gm, '')                      // blockquote
    .replace(/^\s*[-*+][ \t]+/gm, '')                  // list bullets
    .replace(/^\s*\d+[.)][ \t]+/gm, '')                // numbered list
    .replace(/[⚔✦◎⚡⌖⊛]️?/g, '')                 // inline aspect sigils
    .replace(/\n{2,}/g, '. ')                          // paragraph break → pause
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

// ── Browser SpeechSynthesis fallback ────────────────────────────────────────
export function speakReply(text, aspectId) {
  if (!text || typeof speechSynthesis === 'undefined') return;
  const style = TTS_VOICE_STYLES[aspectId] || { rate: 1, pitch: 1 };
  // Project to plain text so the fallback never reads markdown symbols aloud, regardless of caller.
  const u = new SpeechSynthesisUtterance(_speechText(text).slice(0, 4000));
  u.rate = style.rate;
  u.pitch = style.pitch;
  speechSynthesis.speak(u);
}

// ── Voice I/O state ─────────────────────────────────────────────────────────
let _micActive = false;
let _mediaRecorder = null;
let _audioChunks = [];
let _ttsEnabled = false;
let _streamEnabled = false;

//: THE single source of truth for the "speak replies" preference.
//:
//: BL-271: voice.js read `localStorage.getItem('layla_tts') === 'true'` (unset -> OFF) while
//: obsidian.js:121 read `!== 'false'` (unset -> ON). On a fresh profile the second toggle therefore
//: rendered CHECKED while the engine was OFF — the box said one thing and the code did the other, and
//: neither file was wrong on its own. Fixing one line would have left the next copy free to drift, so
//: both now call this. OFF-by-default is the correct default: unexpected speech is a nasty surprise.
export const TTS_STORAGE_KEY = 'layla_tts';

export function readTtsPref() {
  try { return localStorage.getItem(TTS_STORAGE_KEY) === 'true'; } catch (_) { return false; }
}

try {
  _ttsEnabled = readTtsPref();  // opt-in: speaking replies OFF by default
  _streamEnabled = localStorage.getItem('layla_stream') !== 'false';
} catch (_) {}

export function isTtsEnabled() { return _ttsEnabled; }
export function isStreamEnabled() { return _streamEnabled; }

/**
 * BL-270: the missing setter.
 *
 * `speakText` gates on the MODULE-LOCAL `_ttsEnabled`, which was written exactly once at import and
 * never again — no setter was exported. The toggle handler (main.js::toggleTts) could only reach the
 * window mirror, so ticking "Speak replies" updated `window._ttsEnabled`, the checkbox, and
 * localStorage... and then `speakText` consulted the stale module-local and returned early. The toggle
 * SILENTLY DID NOTHING until the page was reloaded.
 *
 * It was invisible because the callers (app.js:655, research.js) check `window._ttsEnabled` — the fresh
 * mirror — and so happily called speakText, which then bailed on the stale copy. Both sides looked
 * correct in isolation. Everything that flips TTS must come through here.
 */
export function setTtsEnabled(on) {
  _ttsEnabled = !!on;
  window._ttsEnabled = _ttsEnabled;  // keep the legacy mirror the callers read
  try { localStorage.setItem(TTS_STORAGE_KEY, _ttsEnabled ? 'true' : 'false'); } catch (_) {}
  return _ttsEnabled;
}

// ── Real availability (BL-272) ──────────────────────────────────────────────
//
// Server TTS is dead unless the optional voice deps are installed: /voice/speak answers 503 and
// /health/deps reports voice_tts:"missing" (verified live on this box). The toggle claimed a capability
// the machine did not have, and what a user actually heard was an undocumented browser speechSynthesis
// fallback: a generic OS voice, truncated at 500 chars, with the speed/volume sliders applying ONLY to
// the dead server path. Three separate lies behind one checkbox.
//
// /health/deps already existed, already worked, and had ZERO UI consumers. So the toggle is now gated on
// it rather than deleted: the operator's own runtime_config.json lists "voice" in setup_features, so
// voice was explicitly asked for — it is one install away, not a fiction. `null` = not yet probed.
let _ttsAvailable = null;

// The one-click install descriptor last seen on a /voice/* 503 (feature id, size, endpoint, the
// GPLv3 kokoro sub-offer). Captured so the Settings install button acts on the SERVER's offer
// rather than a hardcoded guess; falls back to the stable defaults before any 503 is observed.
let _lastInstallOffer = null;

export function isTtsAvailable() { return _ttsAvailable === true; }

function _installOffer() {
  return _lastInstallOffer || {
    feature_id: 'voice',
    endpoint: '/setup/feature/install',
    confirm_payload: { feature_id: 'voice', confirm: true },
    size_mb: 500,
    kokoro: { requires_gpl_accept: true, endpoint: '/voice/tts/kokoro/install' },
  };
}

function _applyTtsAvailability() {
  const available = _ttsAvailable === true;
  const note = available
    ? ''
    : "Voice isn't installed — install it from Settings → Voice & Audio (~500 MB) to enable spoken replies.";

  ['tts-toggle', 'tts-toggle2'].forEach(function (id) {
    const cb = document.getElementById(id);
    if (!cb) return;
    cb.disabled = !available;
    if (!available) cb.checked = false;  // never render CHECKED over a dead engine (BL-271)
    const row = document.getElementById(id + '-row');
    if (row) row.title = available ? 'Speak final reply (Kokoro server TTS)' : note;
  });

  // The sliders drive the SERVER path only. With no server TTS they are decoration.
  ['voice-speed-range', 'voice-volume-range'].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) el.disabled = !available;
  });

  ['tts-note', 'tts-note2'].forEach(function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = note;
    el.hidden = available;
  });

  _ensureInstallAffordance(available);
}

// ── One-click guided install (BL: Voice installable + wired) ─────────────────
//
// When the engine is absent the "Speak replies" toggle is disabled and a note explains why. This
// injects the ACTION that note promises: a permissive [voice] install button (faster-whisper MIT
// + pyttsx3), plus the GPLv3 Kokoro upgrade surfaced ONLY behind an explicit accept toggle. It is
// built in JS (not index.html) so the settings markup needs no new elements, and it is idempotent
// — built once, then shown/hidden by availability.
function _ensureInstallAffordance(available) {
  const anchor = document.getElementById('tts-note2');
  if (!anchor || !anchor.parentNode) return;
  let box = document.getElementById('voice-install-affordance');
  if (available) { if (box) box.hidden = true; return; }
  if (!box) {
    box = document.createElement('div');
    box.id = 'voice-install-affordance';
    box.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:6px';

    const installBtn = document.createElement('button');
    installBtn.type = 'button';
    installBtn.id = 'voice-install-btn';
    installBtn.className = 'tab-btn';
    installBtn.style.cssText = 'font-size:0.7rem';
    installBtn.textContent = 'Install Voice (permissive, ~500 MB)';
    installBtn.title = 'Installs faster-whisper (MIT) + pyttsx3 (system voice). No GPL dependency.';
    installBtn.addEventListener('click', function () { installVoiceFeature(); });
    box.appendChild(installBtn);

    const status = document.createElement('div');
    status.id = 'voice-install-status';
    status.className = 'hint';
    box.appendChild(status);

    // GPLv3 Kokoro upgrade — never bundled by default; gated on an explicit licence accept.
    const gplRow = document.createElement('label');
    gplRow.className = 'option-row';
    gplRow.style.cssText = 'font-size:0.7rem';
    gplRow.title = 'Kokoro is higher quality but GPLv3 (pulls phonemizer-fork). Opt in explicitly.';
    const gplCb = document.createElement('input');
    gplCb.type = 'checkbox';
    gplCb.id = 'voice-kokoro-gpl-accept';
    gplRow.appendChild(gplCb);
    gplRow.appendChild(document.createTextNode(' Accept Kokoro GPLv3 licence (optional, higher-quality TTS)'));
    box.appendChild(gplRow);

    const kokoroBtn = document.createElement('button');
    kokoroBtn.type = 'button';
    kokoroBtn.id = 'voice-install-kokoro-btn';
    kokoroBtn.className = 'tab-btn';
    kokoroBtn.style.cssText = 'font-size:0.7rem';
    kokoroBtn.textContent = 'Install Kokoro neural TTS (GPLv3)';
    kokoroBtn.disabled = true;  // stays dead until GPLv3 is explicitly accepted
    kokoroBtn.addEventListener('click', function () { installKokoroTts(); });
    box.appendChild(kokoroBtn);

    gplCb.addEventListener('change', function () { kokoroBtn.disabled = !gplCb.checked; });

    anchor.parentNode.insertBefore(box, anchor.nextSibling);
  }
  box.hidden = false;
}

/** Install the permissive [voice] feature via the EXISTING allowlisted feature-install endpoint. */
export async function installVoiceFeature() {
  const offer = _installOffer();
  const btn = document.getElementById('voice-install-btn');
  const status = document.getElementById('voice-install-status');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Installing voice engines (this can take a few minutes)…';
  try {
    const resp = await fetch(offer.endpoint || '/setup/feature/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(offer.confirm_payload || { feature_id: 'voice', confirm: true }),
    });
    const d = await resp.json();
    if (d && d.ok) {
      if (status) status.textContent = 'Installed. Enabling…';
      showToast('Voice installed');
    } else {
      const why = (d && (d.error || (d.failed && d.failed[0] && d.failed[0].error))) || 'install failed';
      if (status) status.textContent = 'Install failed: ' + why;
      showToast('Voice install failed');
    }
    await refreshVoiceAvailability();  // re-probe /health/deps; enables the toggle if it landed
    return d;
  } catch (e) {
    if (status) status.textContent = 'Install failed: ' + ((e && e.message) || e);
    showToast('Voice install failed');
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** Install the GPLv3 Kokoro TTS upgrade — refuses unless the accept toggle is ticked. */
export async function installKokoroTts() {
  const cb = document.getElementById('voice-kokoro-gpl-accept');
  const status = document.getElementById('voice-install-status');
  if (!cb || !cb.checked) {
    if (status) status.textContent = 'Accept the Kokoro GPLv3 licence first.';
    return;
  }
  const offer = _installOffer();
  const endpoint = (offer.kokoro && offer.kokoro.endpoint) || '/voice/tts/kokoro/install';
  const btn = document.getElementById('voice-install-kokoro-btn');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Installing Kokoro (GPLv3)…';
  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gpl_accept: true }),  // explicit, informed acceptance
    });
    const d = await resp.json();
    if (d && d.ok) {
      if (status) status.textContent = 'Kokoro installed.';
      showToast('Kokoro TTS installed');
    } else {
      if (status) status.textContent = 'Kokoro install failed: ' + ((d && d.error) || 'failed');
      showToast('Kokoro install failed');
    }
    await refreshVoiceAvailability();
    return d;
  } catch (e) {
    if (status) status.textContent = 'Kokoro install failed: ' + ((e && e.message) || e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** Probe /health/deps and reflect real TTS availability into the controls. */
export async function refreshVoiceAvailability() {
  let ok = false;
  try {
    const r = await fetch('/health/deps');
    const d = await r.json();
    ok = ((d && d.dependencies) || {}).voice_tts === 'ok';
  } catch (_e) {
    ok = false;  // can't confirm the engine exists -> don't claim it does
  }
  _ttsAvailable = ok;
  if (!ok) setTtsEnabled(false);  // a stored `true` from before must not resurrect the robot voice
  _applyTtsAvailability();
  return ok;
}

// ── DOMContentLoaded init ───────────────────────────────────────────────────
export function initVoiceControls() {
  const streamCb = document.getElementById('stream-toggle');
  if (streamCb) {
    streamCb.checked = _streamEnabled;
    streamCb.addEventListener('change', function () {
      _streamEnabled = !!this.checked;
      window._streamEnabled = _streamEnabled;
      localStorage.setItem('layla_stream', _streamEnabled ? 'true' : 'false');
    });
  }
  const ttsCb = document.getElementById('tts-toggle');
  if (ttsCb) ttsCb.checked = _ttsEnabled;

  // Expose onto window for legacy compat reads
  window._ttsEnabled = _ttsEnabled;
  window._streamEnabled = _streamEnabled;
  // Guided-install actions, reachable from the settings panel / delegated handlers.
  window.installVoiceFeature = installVoiceFeature;
  window.installKokoroTts = installKokoroTts;

  refreshVoiceAvailability();
}

// ── Microphone toggle ───────────────────────────────────────────────────────
export async function toggleMic() {
  if (_micActive) {
    stopMic();
  } else {
    await startMic();
  }
}

export async function startMic() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    _mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) _audioChunks.push(e.data);
    };
    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      await transcribeAndSend(blob);
    };
    _mediaRecorder.start();
    _micActive = true;
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.textContent = '⏹';
      micBtn.classList.add('recording');
      micBtn.title = 'Click to stop recording';
    }
  } catch (e) {
    console.error('Mic access denied:', e);
    showToast('Microphone access denied');
  }
}

export function stopMic() {
  if (_mediaRecorder && _micActive) {
    _mediaRecorder.stop();
    _micActive = false;
    const micBtn = document.getElementById('mic-btn');
    if (micBtn) {
      micBtn.textContent = '🎤';
      micBtn.classList.remove('recording');
      micBtn.title = 'Click to record voice';
    }
  }
}

// ── Transcription ───────────────────────────────────────────────────────────
async function transcribeAndSend(blob) {
  const micBtn = document.getElementById('mic-btn');
  if (micBtn) { micBtn.textContent = '⌛'; micBtn.classList.remove('recording'); }
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const resp = await fetch('/voice/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'audio/webm' },
      body: arrayBuffer,
    });
    const data = await resp.json();
    if (data.ok && data.text && data.text.trim()) {
      const input = document.getElementById('msg-input');
      if (input) {
        input.value = data.text.trim();
        if (typeof window.toggleSendButton === 'function') window.toggleSendButton();
        if (typeof window.send === 'function') window.send();
      }
    } else if (resp.status === 503) {
      // Engine not installed: capture the guided-install descriptor and steer to the button.
      if (data && data.install) _lastInstallOffer = data.install;
      showToast("Voice isn't installed — install it in Settings → Voice & Audio");
      refreshVoiceAvailability();
    } else {
      showToast('Could not transcribe audio');
    }
  } catch (e) {
    console.error('Transcription error:', e);
    showToast('Transcription failed');
  } finally {
    if (micBtn) { micBtn.textContent = '🎤'; micBtn.style.color = 'var(--text-dim)'; }
  }
}

// ── Server-side TTS with browser fallback ───────────────────────────────────
export async function speakText(text) {
  if (!_ttsEnabled || !text) return;
  // BL-272: with no server TTS installed, do NOT quietly substitute the browser's generic OS voice.
  // That fallback is what made the dead toggle look alive: it spoke, so nothing seemed broken, while the
  // speed/volume sliders (server-only) did nothing and the text was silently cut at 500 chars. The
  // fallback below is kept for its real job — a network/decode failure when the engine IS installed.
  if (_ttsAvailable === false) return;
  try {
    const asp = appState.get('aspect.current') || 'morrigan';
    // Speed slider now reaches the server (was ignored). The server treats an
    // explicit speed as an override of the per-aspect default.
    let spd = null;
    try { const s = parseFloat(localStorage.getItem('layla_voice_speed')); if (isFinite(s) && s > 0) spd = Math.max(0.5, Math.min(2, s)); } catch (_) {}
    const speakBody = { text, aspect_id: asp };
    if (spd != null) speakBody.speed = spd;
    const resp = await fetch('/voice/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(speakBody),
    });
    if (resp.ok) {
      const arrayBuffer = await resp.arrayBuffer();
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      const source = audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      // Volume: route through a GainNode (was wired straight to destination, so the
      // volume slider did nothing). Reads the saved 0..1 volume.
      let vol = 1;
      try { const raw = parseFloat(localStorage.getItem('layla_voice_volume')); if (isFinite(raw)) vol = Math.max(0, Math.min(1, raw)); } catch (_) {}
      const gain = audioCtx.createGain();
      gain.gain.value = vol;
      source.connect(gain);
      gain.connect(audioCtx.destination);
      source.start();
      return;
    }
  } catch (_) { /* network error; fall through to browser TTS */ }
  if (typeof speechSynthesis !== 'undefined') {
    try {
      speakReply(text.slice(0, 500), appState.get('aspect.current') || 'morrigan');
    } catch (_) {}
  }
}

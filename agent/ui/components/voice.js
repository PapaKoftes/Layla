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

try {
  _ttsEnabled = localStorage.getItem('layla_tts') === 'true';  // opt-in: speaking replies OFF by default
  _streamEnabled = localStorage.getItem('layla_stream') !== 'false';
} catch (_) {}

export function isTtsEnabled() { return _ttsEnabled; }
export function isStreamEnabled() { return _streamEnabled; }

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

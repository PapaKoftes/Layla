/**
 * layla-voice.js — Voice recording, TTS playback, and audio controls.
 * Depends on: layla-utils.js (showToast, fetchWithTimeout), layla-aspect.js (ASPECT_COLORS)
 */
(function () {
  'use strict';

  // Aspect → TTS voice style (rate, pitch) for browser SpeechSynthesis fallback
  var TTS_VOICE_STYLES = {
    morrigan:  { rate: 1.05, pitch: 0.90 },
    nyx:       { rate: 0.82, pitch: 0.88 },
    eris:      { rate: 1.20, pitch: 1.12 },
    echo:      { rate: 0.90, pitch: 1.10 },
    cassandra: { rate: 1.15, pitch: 1.05 },
    lilith:    { rate: 0.78, pitch: 0.88 },
  };
  window.TTS_VOICE_STYLES = TTS_VOICE_STYLES;

  function speakReply(text, aspectId) {
    if (!text || typeof speechSynthesis === 'undefined') return;
    var style = TTS_VOICE_STYLES[aspectId] || { rate: 1, pitch: 1 };
    var u = new SpeechSynthesisUtterance(text.slice(0, 4000));
    u.rate = style.rate;
    u.pitch = style.pitch;
    speechSynthesis.speak(u);
  }
  window.speakReply = speakReply;

  // ── Voice I/O state ────────────────────────────────────────────────────────
  var _micActive = false;
  var _mediaRecorder = null;
  var _audioChunks = [];
  window._ttsEnabled = localStorage.getItem('layla_tts') !== 'false';
  window._streamEnabled = localStorage.getItem('layla_stream') !== 'false';

  document.addEventListener('DOMContentLoaded', function () {
    var streamCb = document.getElementById('stream-toggle');
    if (streamCb) {
      streamCb.checked = window._streamEnabled;
      streamCb.addEventListener('change', function () {
        window._streamEnabled = !!this.checked;
        localStorage.setItem('layla_stream', window._streamEnabled ? 'true' : 'false');
      });
    }
    var ttsCb = document.getElementById('tts-toggle');
    if (ttsCb) ttsCb.checked = window._ttsEnabled;
    try {
      var asp = (typeof window.currentAspect !== 'undefined') ? window.currentAspect : 'morrigan';
      if (typeof window.laylaSetAspectSprite === 'function') window.laylaSetAspectSprite(asp);
    } catch (_) {}
    try { if (typeof refreshMaturityCard === 'function') refreshMaturityCard(false); } catch (_) {}
  });

  async function toggleMic() {
    if (_micActive) {
      stopMic();
    } else {
      await startMic();
    }
  }
  window.toggleMic = toggleMic;

  async function startMic() {
    try {
      var stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      _audioChunks = [];
      _mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      _mediaRecorder.ondataavailable = function (e) { if (e.data.size > 0) _audioChunks.push(e.data); };
      _mediaRecorder.onstop = async function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        var blob = new Blob(_audioChunks, { type: 'audio/webm' });
        await transcribeAndSend(blob);
      };
      _mediaRecorder.start();
      _micActive = true;
      var micBtn = document.getElementById('mic-btn');
      if (micBtn) {
        micBtn.textContent = '⏹';
        micBtn.classList.add('recording');
        micBtn.title = 'Click to stop recording';
      }
    } catch (e) {
      console.error('Mic access denied:', e);
      if (typeof showToast === 'function') showToast('Microphone access denied');
    }
  }

  function stopMic() {
    if (_mediaRecorder && _micActive) {
      _mediaRecorder.stop();
      _micActive = false;
      var micBtn = document.getElementById('mic-btn');
      if (micBtn) {
        micBtn.textContent = '🎤';
        micBtn.classList.remove('recording');
        micBtn.title = 'Click to record voice';
      }
    }
  }
  window.stopMic = stopMic;

  async function transcribeAndSend(blob) {
    var micBtn = document.getElementById('mic-btn');
    if (micBtn) { micBtn.textContent = '⌛'; micBtn.classList.remove('recording'); }
    try {
      var arrayBuffer = await blob.arrayBuffer();
      var resp = await fetch('/voice/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'audio/webm' },
        body: arrayBuffer,
      });
      var data = await resp.json();
      if (data.ok && data.text && data.text.trim()) {
        var input = document.getElementById('msg-input');
        if (input) {
          input.value = data.text.trim();
          if (typeof toggleSendButton === 'function') toggleSendButton();
          if (typeof send === 'function') send();
        }
      } else {
        if (typeof showToast === 'function') showToast('Could not transcribe audio');
      }
    } catch (e) {
      console.error('Transcription error:', e);
      if (typeof showToast === 'function') showToast('Transcription failed');
    } finally {
      if (micBtn) { micBtn.textContent = '🎤'; micBtn.style.color = 'var(--text-dim)'; }
    }
  }

  async function speakText(text) {
    if (!window._ttsEnabled || !text) return;
    try {
      var _asp = (typeof window.currentAspect !== 'undefined' ? window.currentAspect : 'morrigan') || 'morrigan';
      var resp = await fetch('/voice/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text, aspect_id: _asp }),
      });
      if (resp.ok) {
        var arrayBuffer = await resp.arrayBuffer();
        var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        var audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        var source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioCtx.destination);
        source.start();
        return;
      }
    } catch (e) { /* network error; fall through */ }
    if (typeof speechSynthesis !== 'undefined') {
      try { speakReply(text.slice(0, 500), window.currentAspect || 'morrigan'); } catch (_) {}
    }
  }
  window.speakText = speakText;

  window.laylaVoiceModuleLoaded = true;
})();

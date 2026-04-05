/**
 * Per-aspect neon line-art sprites (background). Loaded before layla-app.js.
 */
(function () {
  'use strict';

  var SPRITES = {
    morrigan: '/layla-ui/assets/sprites/morrigan.svg',
    nyx: '/layla-ui/assets/sprites/nyx.svg',
    echo: '/layla-ui/assets/sprites/echo.svg',
    eris: '/layla-ui/assets/sprites/eris.svg',
    cassandra: '/layla-ui/assets/sprites/cassandra.svg',
    lilith: '/layla-ui/assets/sprites/lilith.svg',
  };

  function laylaSetAspectSprite(aspectId) {
    var field = document.getElementById('layla-sprite-field');
    if (!field) return;
    var id = String(aspectId || 'morrigan').toLowerCase();
    var src = SPRITES[id] || SPRITES.morrigan;
    var img = field.querySelector('img.layla-aspect-sprite');
    if (!img) {
      img = document.createElement('img');
      img.className = 'layla-aspect-sprite';
      img.alt = '';
      img.setAttribute('aria-hidden', 'true');
      img.decoding = 'async';
      field.appendChild(img);
    }
    if (img.getAttribute('src') !== src) {
      field.classList.add('is-switching');
      var done = function () {
        field.classList.remove('is-switching');
      };
      img.onload = done;
      img.onerror = done;
      img.setAttribute('src', src);
      setTimeout(done, 400);
    }
  }

  window.laylaSetAspectSprite = laylaSetAspectSprite;
})();

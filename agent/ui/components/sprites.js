/**
 * components/sprites.js — Per-aspect neon line-art sprite backgrounds.
 *
 * Converted from js/layla-sprites.js (IIFE → ES module).
 */

const SPRITES = {
  morrigan:  '/layla-ui/assets/sprites/morrigan.svg',
  nyx:       '/layla-ui/assets/sprites/nyx.svg',
  echo:      '/layla-ui/assets/sprites/echo.svg',
  eris:      '/layla-ui/assets/sprites/eris.svg',
  cassandra: '/layla-ui/assets/sprites/cassandra.svg',
  lilith:    '/layla-ui/assets/sprites/lilith.svg',
};

export function setAspectSprite(aspectId) {
  const field = document.getElementById('layla-sprite-field');
  if (!field) return;
  const id = String(aspectId || 'morrigan').toLowerCase();
  const src = SPRITES[id] || SPRITES.morrigan;
  let img = field.querySelector('img.layla-aspect-sprite');
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
    const done = () => field.classList.remove('is-switching');
    img.onload = done;
    img.onerror = done;
    img.setAttribute('src', src);
    setTimeout(done, 400);
  }
}

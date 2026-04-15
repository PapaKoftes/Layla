/**
 * Thin API helpers (debug / panels). Main app keeps fetchWithTimeout in layla-app.js for now.
 */
(function () {
  'use strict';
  window.laylaApiJson = function (url, opts) {
    opts = opts || {};
    return fetch(url, opts).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, json: j }; }); });
  };
})();

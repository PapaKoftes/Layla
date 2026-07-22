/**
 * components/custom-aspect.js — create your own aspect (REQ-79 / BL-092).
 *
 * A custom aspect is a named persona that inherits behaviour/voice from a base built-in and
 * overrides name, sigil (symbol), tagline, accent, and a prompt hint. Surfaces the additive
 * /character/custom-aspects backend. Overlay shell + G1 tokens. ⌘K → "Create custom aspect".
 */

import { setAspect } from "./aspect.js";

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
async function _send(url, method, body) {
  return (await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })).json();
}

// BL-386: Escape must work regardless of where focus sits. A listener on _root only fires when the
// keydown target is _root or a descendant; on first-run / just-opened, focus is on <body>, so a _root
// listener never receives it and the "esc" chip advertised an exit that never fired. Listen on
// document (capture), added on open and removed on close so it can never accumulate across opens.
function _onDocKeydown(e) {
  if (!_open) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeCustomAspect(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "customaspect";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Create custom aspect");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel ca-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">✦</span>' +
        '<span class="sysdiag-title">create custom aspect</span>' +
        '<button type="button" class="sysdiag-refresh ca-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="ca-form">' +
        '<div class="ca-row"><input type="text" class="ca-id" placeholder="id (lowercase, e.g. sable)" maxlength="32" />' +
          '<input type="text" class="ca-name" placeholder="name (e.g. Sable)" maxlength="60" /></div>' +
        '<div class="ca-row"><input type="text" class="ca-symbol" placeholder="sigil (e.g. ☾)" maxlength="8" />' +
          '<select class="ca-base" title="inherit behaviour/voice from"></select></div>' +
        '<input type="text" class="ca-tagline" placeholder="tagline (optional)" maxlength="200" />' +
        '<textarea class="ca-prompt" rows="2" placeholder="prompt hint — how she should behave as this aspect (optional)"></textarea>' +
        '<div class="ca-row"><input type="text" class="ca-color" placeholder="accent #hex (optional)" maxlength="32" />' +
          '<button type="button" class="ca-create setup-btn primary">create aspect</button></div>' +
        '<div class="ca-note"></div>' +
      "</div>" +
      '<div class="ca-list"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeCustomAspect(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeCustomAspect(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeCustomAspect());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeCustomAspect(); } });
  }
  _root.querySelector(".ca-refresh").addEventListener("click", _load);
  _root.querySelector(".ca-create").addEventListener("click", _create);
}

async function _load() {
  const list = _root.querySelector(".ca-list");
  list.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/character/custom-aspects");
    // fill the base-aspect dropdown once
    const sel = _root.querySelector(".ca-base");
    if (sel && !sel.options.length) {
      sel.innerHTML = (d.base_aspects || []).map((b) => '<option value="' + _esc(b) + '">inherit: ' + _esc(b) + "</option>").join("");
    }
    const customs = d.custom || [];
    if (!customs.length) { list.innerHTML = '<div class="sysdiag-muted">no custom aspects yet — create one above</div>'; return; }
    list.innerHTML = '<div class="ca-listtitle">your custom aspects</div>' + customs.map((c) =>
      '<div class="ca-item"><span class="ca-sigil">' + _esc(c.symbol || "✦") + "</span>" +
      '<span class="ca-itemmain"><span class="ca-itemname">' + _esc(c.name || c.id) + "</span>" +
      '<span class="ca-itemsub">' + _esc(c.id) + " · inherits " + _esc(c.base_aspect || "") + (c.tagline ? " · " + _esc(c.tagline) : "") + "</span></span>" +
      '<button type="button" class="ca-use setup-btn" data-id="' + _esc(c.id) + '" data-name="' + _esc(c.name || c.id) + '">talk as this</button>' +
      '<button type="button" class="ca-del" data-id="' + _esc(c.id) + '">delete</button></div>'
    ).join("");
    // BL-301: "talk as this" is the missing switch — it makes the custom aspect the ACTIVE one, so
    // the next turn's request carries aspect_id=<custom> and select_aspect resolves it (the backend
    // fix). Without this the create/delete UI offered a persona you could never actually select.
    list.querySelectorAll(".ca-use").forEach((b) => b.addEventListener("click", () => _use(b.getAttribute("data-id"), b.getAttribute("data-name"))));
    list.querySelectorAll(".ca-del").forEach((b) => b.addEventListener("click", () => _del(b.getAttribute("data-id"))));
  } catch (e) {
    list.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _create() {
  const note = _root.querySelector(".ca-note");
  const spec = {
    id: (_root.querySelector(".ca-id").value || "").trim().toLowerCase(),
    name: (_root.querySelector(".ca-name").value || "").trim(),
    symbol: (_root.querySelector(".ca-symbol").value || "").trim(),
    base_aspect: _root.querySelector(".ca-base").value || "morrigan",
    tagline: (_root.querySelector(".ca-tagline").value || "").trim(),
    prompt_hint: (_root.querySelector(".ca-prompt").value || "").trim(),
    color_primary: (_root.querySelector(".ca-color").value || "").trim(),
  };
  if (!spec.id) { note.textContent = "id is required"; note.removeAttribute("data-ok"); return; }
  note.textContent = "creating…";
  try {
    const d = await _send("/character/custom-aspects", "POST", spec);
    if (d.ok === false) { note.textContent = "error — " + (d.error || "failed"); note.removeAttribute("data-ok"); return; }
    note.textContent = "✓ created — " + (d.aspect ? d.aspect.name : spec.id);
    note.setAttribute("data-ok", "true");
    ["ca-id", "ca-name", "ca-symbol", "ca-tagline", "ca-prompt", "ca-color"].forEach((c) => { const el = _root.querySelector("." + c); if (el) el.value = ""; });
    if (window.showToast) window.showToast("Custom aspect created");
    _load();
  } catch (e) {
    note.textContent = "error — " + (e && e.message ? e.message : e);
  }
}

function _use(id, name) {
  if (!id) return;
  try { setAspect(id, true); } catch (_) {}
  try { if (window.showToast) window.showToast("Now talking to " + (name || id)); } catch (_) {}
  closeCustomAspect();
}

async function _del(id) {
  if (!id) return;
  try { await _send("/character/custom-aspects/" + encodeURIComponent(id), "DELETE"); } catch (_) {}
  _load();
}

export function openCustomAspect() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeCustomAspect() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

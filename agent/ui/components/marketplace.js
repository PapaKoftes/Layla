/**
 * components/marketplace.js — kit marketplace (UPG-37 / BL-156).
 *
 * Browse curated capability kits by category and install in one click. A kit enables a bundle
 * of features (deps/models/flags) via /kits/install. Surfaces /kits/catalog with an installed
 * badge. Overlay shell + G1 tokens. ⌘K → "Kit marketplace".
 */

import { laylaConfirm } from "../services/utils.js";

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
async function _post(url, body) {
  return (await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })).json();
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "marketplace";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Kit marketplace");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel mkt-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">◈</span>' +
        '<span class="sysdiag-title">kit marketplace</span>' +
        '<button type="button" class="sysdiag-refresh mkt-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="mkt-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeMarketplace(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeMarketplace(); } });
  _root.querySelector(".mkt-refresh").addEventListener("click", _load);
}

async function _load() {
  const body = _root.querySelector(".mkt-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/kits/catalog");
    const kits = d.kits || [];
    const installed = d.installed || {};
    if (!kits.length) { body.innerHTML = '<div class="sysdiag-muted">no kits</div>'; return; }
    const cats = {};
    kits.forEach((k) => { (cats[k.category || "other"] = cats[k.category || "other"] || []).push(k); });
    body.innerHTML = Object.keys(cats).sort().map((cat) =>
      '<div class="mkt-cat">' + _esc(cat) + "</div>" +
      cats[cat].map((k) => {
        const on = installed[k.id];
        const feats = (k.features || []).join(", ");
        return '<div class="mkt-kit' + (on ? " is-on" : "") + '">' +
          '<span class="mkt-icon" aria-hidden="true">' + _esc(k.icon || "◆") + "</span>" +
          '<span class="mkt-main"><span class="mkt-name">' + _esc(k.name || k.id) + "</span>" +
          '<span class="mkt-desc">' + _esc(k.desc || "") + "</span>" +
          (feats ? '<span class="mkt-feats">' + _esc(feats) + "</span>" : "") + "</span>" +
          (on
            ? '<span class="mkt-installed">✓ installed</span>'
            : '<button type="button" class="mkt-install setup-btn" data-id="' + _esc(k.id) + '">install</button>') +
          '<span class="mkt-status" data-status-for="' + _esc(k.id) + '" hidden></span>' +
          "</div>";
      }).join("")
    ).join("");
    body.querySelectorAll(".mkt-install").forEach((b) => b.addEventListener("click", () => _install(b, b.getAttribute("data-id"))));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

function _setStatus(kitId, text, kind) {
  const el = _root.querySelector('[data-status-for="' + CSS.escape(kitId) + '"]');
  if (!el) return;
  el.hidden = !text;
  el.textContent = text || "";
  el.setAttribute("data-kind", kind || "");
}

function _sizeLabel(mb) {
  if (!mb) return "";
  return mb >= 1000 ? (mb / 1000).toFixed(1) + " GB" : mb + " MB";
}

/**
 * The last MEANINGFUL line of an error blob.
 *
 * `String(err).split("\n").slice(-1)[0]` looks right and is wrong for the exact input this
 * always receives: pip stderr ends with a trailing newline, so the last element is "" and the
 * row rendered "✕ Voice (speak & listen)  faster-whisper:  | kokoro-onnx:" — red styling, no
 * reason. Walk back past the blank lines and keep a fallback, so a failure is never silent.
 */
function _lastLine(err) {
  const lines = String(err == null ? "" : err).split("\n").map((s) => s.trim()).filter(Boolean);
  return lines.length ? lines[lines.length - 1] : "install failed (no error text)";
}

/**
 * Install a kit — for real, and with the truth on screen.
 *
 * This used to POST confirm:true and toast "Installed <kit>" on any non-false `ok`, while the
 * backend's confirm branch discarded the install plan and only flipped config flags. So every
 * dep-bearing kit (Voice Companion, Quality ML Stack, Privacy Vault, Researcher) reported a
 * successful install that had not happened. Now: the plan (with download size) is shown and
 * consented to first, progress is visible while pip runs, and a failure prints the package
 * that failed and why — the kit is not marked installed unless it is.
 */
async function _install(btn, kitId) {
  if (!kitId) return;
  const restore = () => { btn.disabled = false; btn.textContent = "retry"; };
  btn.disabled = true;
  try {
    // 1. Plan first (no confirm) so the operator sees what is about to be downloaded.
    btn.textContent = "checking…";
    _setStatus(kitId, "", "");
    const plan = await _post("/kits/install", { kit_id: kitId });
    if (plan.ok === false) {
      restore();
      _setStatus(kitId, plan.error || "could not read the install plan", "err");
      return;
    }
    const toInstall = plan.to_install || [];
    const pkgs = toInstall.reduce((a, f) => a.concat(f.deps || []), []);
    const mb = toInstall.reduce((a, f) => a + (f.size_mb || 0), 0);
    if (pkgs.length) {
      const ask = "Install " + pkgs.join(", ") + (mb ? " (~" + _sizeLabel(mb) + " download)" : "") + "?";
      if (!(await laylaConfirm(ask))) { btn.disabled = false; btn.textContent = "install"; return; }
    }

    // 2. Run it. pip is slow and network-bound — keep the row talking.
    btn.textContent = "installing…";
    _setStatus(kitId, pkgs.length ? "downloading " + pkgs.join(", ") + " — this can take a few minutes…" : "enabling…", "busy");
    const d = await _post("/kits/install", { kit_id: kitId, confirm: true });

    if (d.ok === false) {
      restore();
      const why = (d.failed && d.failed.length)
        ? d.failed.map((x) => x.dep + ": " + _lastLine(x.error)).join(" | ")
        : (d.error || "install failed");
      _setStatus(kitId, "not installed — " + why, "err");
      if (window.showToast) window.showToast("Install failed: " + why);
      return;
    }
    _setStatus(kitId, "", "");
    if (window.showToast) window.showToast("Installed " + kitId);
    _load();
  } catch (e) {
    restore();
    _setStatus(kitId, "install failed — " + (e && e.message ? e.message : e), "err");
  }
}

export function openMarketplace() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _load();
}

export function closeMarketplace() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

/**
 * components/marketplace.js — kit marketplace (UPG-37 / BL-156).
 *
 * Browse curated capability kits by category and install in one click. A kit enables a bundle
 * of features (deps/models/flags) via /kits/install. Surfaces /kits/catalog with an installed
 * badge. Overlay shell + G1 tokens. ⌘K → "Kit marketplace".
 */

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
          "</div>";
      }).join("")
    ).join("");
    body.querySelectorAll(".mkt-install").forEach((b) => b.addEventListener("click", () => _install(b, b.getAttribute("data-id"))));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _install(btn, kitId) {
  if (!kitId) return;
  btn.disabled = true;
  btn.textContent = "installing…";
  try {
    const d = await _post("/kits/install", { kit_id: kitId, confirm: true });
    if (d.ok === false) { btn.disabled = false; btn.textContent = "retry"; if (window.showToast) window.showToast("Install failed: " + (d.error || "")); return; }
    if (window.showToast) window.showToast("Installed " + kitId);
    _load();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "retry";
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

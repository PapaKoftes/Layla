/**
 * components/journal.js — Layla's journal (W2 BL-042).
 *
 * Surfaces the /journal backend that had no UI: read her entries and add one. Reuses the
 * overlay shell + G1 tokens; relative fetches (auth via the patched fetch). ⌘K → "Journal".
 */

let _root = null;
let _open = false;

const _TYPES = ["note", "reflection", "insight", "mood", "milestone"];

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function _get(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  return r.json();
}
async function _post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return r.json();
}

// BL-386: Escape must work regardless of where focus sits. A listener on _root only fires when the
// keydown target is _root or a descendant; on first-run / just-opened, focus is on <body>, so a _root
// listener never receives it and the "esc" chip advertised an exit that never fired. Listen on
// document (capture), added on open and removed on close so it can never accumulate across opens.
function _onDocKeydown(e) {
  if (!_open) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeJournal(); }
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "journal";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Journal");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel journal-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">✎</span>' +
        '<span class="sysdiag-title">journal</span>' +
        '<button type="button" class="sysdiag-refresh journal-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="journal-add">' +
        '<select class="journal-type">' + _TYPES.map((t) => "<option>" + t + "</option>").join("") + "</select>" +
        '<textarea class="journal-content" rows="2" placeholder="write an entry…"></textarea>' +
        '<button type="button" class="journal-save setup-btn primary">add</button></div>' +
      '<div class="journal-list"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeJournal(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeJournal(); } });
  // BL-386: the "esc" chip advertised an exit — make it actually dismiss (click + keyboard).
  const _escChip = _root.querySelector(".cmdp-esc");
  if (_escChip) {
    _escChip.setAttribute("role", "button");
    _escChip.setAttribute("tabindex", "0");
    _escChip.setAttribute("aria-label", "Close");
    _escChip.addEventListener("click", () => closeJournal());
    _escChip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); closeJournal(); } });
  }
  _root.querySelector(".journal-refresh").addEventListener("click", _load);
  _root.querySelector(".journal-save").addEventListener("click", _add);
}

function _entriesFrom(d) {
  if (Array.isArray(d)) return d;
  return d.entries || d.records || d.items || [];
}

function _load() {
  const list = _root.querySelector(".journal-list");
  list.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  _get("/journal?limit=60").then((d) => {
    const entries = _entriesFrom(d);
    if (!entries.length) { list.innerHTML = '<div class="sysdiag-muted">no entries yet</div>'; return; }
    list.innerHTML = entries.map((e) => {
      const when = e.created_at || e.day || e.timestamp || "";
      return '<div class="journal-entry"><div class="journal-entry-head">' +
        '<span class="journal-etype">' + _esc(e.entry_type || e.type || "note") + "</span>" +
        '<span class="journal-when">' + _esc(String(when).slice(0, 19).replace("T", " ")) + "</span></div>" +
        '<div class="journal-etext">' + _esc(e.content || e.text || "") + "</div></div>";
    }).join("");
  }).catch((e) => { list.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>"; });
}

async function _add() {
  const content = (_root.querySelector(".journal-content").value || "").trim();
  if (!content) return;
  const entry_type = _root.querySelector(".journal-type").value;
  _root.querySelector(".journal-content").value = "";
  try { await _post("/journal", { entry_type, content }); if (window.showToast) window.showToast("Entry added"); } catch (_) {}
  _load();
}

export function openJournal() {
  _build();
  if (_open) return;
  _open = true;
  document.addEventListener("keydown", _onDocKeydown, true); // BL-386: authoritative Escape (document-level)
  _root.hidden = false;
  _load();
}

export function closeJournal() {
  if (!_root || !_open) return;
  _open = false;
  document.removeEventListener("keydown", _onDocKeydown, true); // BL-386: no listener leak across opens
  _root.hidden = true;
}

/**
 * components/kb.js — knowledge base (W2 BL-045).
 *
 * Surfaces the /intelligence/kb/* backend that had no UI: browse KB articles, read one,
 * and build new ones from pasted text. Reuses the overlay shell + G1 tokens; relative
 * fetches. ⌘K → "Knowledge base".
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
  _root.id = "kb";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Knowledge base");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel kb-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">❋</span>' +
        '<span class="sysdiag-title">knowledge base</span>' +
        '<span class="kb-count"></span>' +
        '<button type="button" class="sysdiag-refresh kb-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="kb-build"><textarea class="kb-text" rows="2" placeholder="paste text to build an article…"></textarea>' +
        '<div class="kb-buildrow"><input type="text" class="kb-topic" placeholder="topic (optional)" />' +
        '<button type="button" class="kb-buildbtn setup-btn primary">build</button></div></div>' +
      '<div class="kb-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeKb(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeKb(); } });
  _root.querySelector(".kb-refresh").addEventListener("click", _loadList);
  _root.querySelector(".kb-buildbtn").addEventListener("click", _buildArticle);
}

function _articlesFrom(d) {
  if (Array.isArray(d)) return d;
  return d.articles || d.items || d.records || [];
}

async function _loadList() {
  const body = _root.querySelector(".kb-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/intelligence/kb/articles");
    const arts = _articlesFrom(d);
    const cnt = _root.querySelector(".kb-count");
    if (cnt) cnt.textContent = arts.length + " articles";
    if (!arts.length) { body.innerHTML = '<div class="sysdiag-muted">no articles — build one above</div>'; return; }
    body.innerHTML = '<div class="kb-list">' + arts.map((a) =>
      '<button type="button" class="kb-artbtn" data-id="' + _esc(a.id || a.article_id || a.slug || "") + '">' +
      '<span class="kb-arttitle">' + _esc(a.title || a.topic || a.id) + "</span>" +
      (a.topic && a.title ? '<span class="kb-arttopic">' + _esc(a.topic) + "</span>" : "") + "</button>"
    ).join("") + "</div>";
    body.querySelectorAll(".kb-artbtn").forEach((b) => b.addEventListener("click", () => _openArticle(b.getAttribute("data-id"), b.querySelector(".kb-arttitle").textContent)));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _openArticle(id, title) {
  if (!id) return;
  const body = _root.querySelector(".kb-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/intelligence/kb/articles/" + encodeURIComponent(id));
    const art = d.article || d;
    const content = art.content || art.body || art.text || art.summary || "";
    body.innerHTML =
      '<button type="button" class="kb-back">‹ back</button>' +
      '<div class="kb-detail"><div class="kb-dtitle">' + _esc(art.title || title || id) + "</div>" +
      '<div class="kb-dcontent">' + _esc(content) + "</div></div>";
    body.querySelector(".kb-back").addEventListener("click", _loadList);
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _buildArticle() {
  const text = (_root.querySelector(".kb-text").value || "").trim();
  const topic = (_root.querySelector(".kb-topic").value || "").trim();
  if (!text) return;
  const body = _root.querySelector(".kb-body");
  body.innerHTML = '<div class="sysdiag-muted">building… (synthesizes articles from the text)</div>';
  _root.querySelector(".kb-text").value = "";
  try { await _post("/intelligence/kb/build/text", { texts: [text], topic }); if (window.showToast) window.showToast("KB build started"); } catch (_) {}
  _loadList();
}

export function openKb() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _loadList();
}

export function closeKb() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

/**
 * components/graph.js — knowledge-graph viewer.
 *
 * Surfaces the /graph/* backend that had no UI at all. layla/memory/memory_graph.py has been
 * writing entities and auto-linking them (`similar_to` edges) since the memory layer existed;
 * nothing ever read them back, so the whole entity/relationship graph was invisible to the
 * person it describes. This panel is the read path: stats, a searchable entity list, and one
 * entity's relationships as clickable chips you can walk.
 *
 * Deliberately NOT a force-directed canvas. A spring layout over a few thousand `similar_to`
 * edges is a hairball that answers no question; list → detail → walk the chips answers "what
 * does she think is connected to this, and why".
 *
 * Read-only by construction — the router exposes no mutation endpoints. Reuses the overlay
 * shell + G1 tokens; relative fetches; scoped styles injected once (same pattern as search.js).
 * ⌘K → "Knowledge graph".
 */

let _root = null;
let _open = false;
let _stylesInjected = false;
let _qTimer = null;
let _offset = 0;
let _matched = 0;
const _LIMIT = 50;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function _get(url) {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  return r.json();
}

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const s = document.createElement("style");
  s.textContent = `
    .graph-panel { max-width: 640px; }
    .graph-count { flex: none; font-size: var(--text-xs); color: var(--text-dim); margin-left: auto; margin-right: 8px; }
    .graph-qrow { padding: var(--sp-2) var(--sp-4); border-bottom: 1px solid var(--border); }
    .graph-q {
      width: 100%; box-sizing: border-box; background: var(--surface-2); color: var(--text);
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      font-family: 'JetBrains Mono', monospace; font-size: var(--text-xs); padding: var(--sp-2) var(--sp-3);
    }
    .graph-q:focus { outline: none; border-color: color-mix(in srgb, var(--accent) 50%, var(--border)); }
    .graph-body { max-height: 56vh; overflow-y: auto; padding: 8px 12px; display: flex; flex-direction: column; gap: 10px; }
    .graph-list { display: flex; flex-direction: column; gap: 4px; }
    .graph-ebtn {
      display: flex; flex-direction: column; align-items: flex-start; gap: 3px; width: 100%;
      text-align: left; background: var(--surface-2); border: 1px solid var(--border);
      border-radius: var(--radius-sm); color: var(--text); font-family: inherit; padding: 8px 12px; cursor: pointer;
    }
    .graph-ebtn:hover, .graph-ebtn:focus-visible { border-color: var(--accent-text); background: var(--surface-3); }
    .graph-elabel { font-size: var(--text-sm); overflow-wrap: anywhere; }
    .graph-emeta { font-size: var(--text-xs); color: var(--text-dim); font-family: 'JetBrains Mono', monospace; }
    .graph-chips { display: flex; flex-wrap: wrap; gap: 4px; }
    .graph-chip {
      font-size: var(--text-xs); font-family: 'JetBrains Mono', monospace; color: var(--text-dim);
      border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; background: transparent;
    }
    button.graph-chip { cursor: pointer; color: var(--accent-text); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
    button.graph-chip:hover, button.graph-chip:focus-visible { background: var(--surface-3); color: var(--text); }
    .graph-rel { display: flex; align-items: baseline; gap: 6px; padding: 3px 0; font-size: var(--text-sm); flex-wrap: wrap; }
    .graph-relname { font-size: var(--text-xs); font-family: 'JetBrains Mono', monospace; color: var(--text-faint); }
    .graph-more { width: 100%; background: var(--surface-2); border: 1px dashed var(--border); color: var(--text-dim);
      border-radius: var(--radius-sm); font-family: inherit; font-size: var(--text-xs); padding: 6px 10px; cursor: pointer; }
    .graph-more:hover { color: var(--text); border-color: var(--accent-text); }
    .graph-back { background: none; border: none; color: var(--accent-text); font-family: inherit;
      font-size: var(--text-sm); cursor: pointer; padding: 4px 0; align-self: flex-start; }
    .graph-back:hover { text-decoration: underline; }
    .graph-dtitle { font-size: var(--text-md); font-weight: 700; color: var(--accent-text); overflow-wrap: anywhere; }
    .graph-sec-title { font-size: var(--text-xs); text-transform: lowercase; letter-spacing: 0.08em; color: var(--text-faint); }
  `;
  document.head.appendChild(s);
}

function _build() {
  if (_root) return;
  _injectStyles();
  _root = document.createElement("div");
  _root.id = "graph";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Knowledge graph");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel graph-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">◈</span>' +
        '<span class="sysdiag-title" data-i18n="nav.knowledge_graph">Knowledge graph</span>' +
        '<span class="graph-count"></span>' +
        '<button type="button" class="sysdiag-refresh graph-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="graph-qrow">' +
        '<input type="search" class="graph-q" aria-label="Search entities" data-i18n-placeholder="pui.search_entities" placeholder="search entities…" />' +
      "</div>" +
      '<div class="graph-body" role="region" aria-live="polite" aria-label="Knowledge graph contents"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeGraph(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeGraph(); } });
  _root.querySelector(".graph-refresh").addEventListener("click", () => _loadList());
  const q = _root.querySelector(".graph-q");
  q.addEventListener("input", () => {
    clearTimeout(_qTimer);
    _qTimer = setTimeout(() => _loadList(), 220);
  });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(_qTimer); _loadList(); } });
}

function _query() {
  return ((_root.querySelector(".graph-q") || {}).value || "").trim();
}

function _statsHtml(st) {
  if (!st || st.ok === false) {
    return '<div class="sysdiag-err">stats unavailable</div>';
  }
  const rels = (st.relation_counts || []).slice(0, 8);
  return (
    '<div class="sysdiag-card"><div class="sysdiag-card-title">graph</div><div class="sysdiag-body">' +
      '<div class="sysdiag-row"><span class="k">entities</span><span class="v">' + _esc(st.entity_count) + "</span></div>" +
      '<div class="sysdiag-row"><span class="k">relationships</span><span class="v">' + _esc(st.relationship_count) + "</span></div>" +
      '<div class="sysdiag-row"><span class="k">unconnected</span><span class="v">' + _esc(st.isolated_count) + "</span></div>" +
      (rels.length
        ? '<div class="sysdiag-row"><span class="k">by type</span><span class="v"><span class="graph-chips">' +
          rels.map((r) => '<span class="graph-chip">' + _esc(r.relation) + " ×" + _esc(r.count) + "</span>").join("") +
          "</span></span></div>"
        : "") +
    "</div></div>"
  );
}

function _entityRow(e) {
  const bits = [];
  if (e.degree) bits.push(e.degree + (e.degree === 1 ? " link" : " links"));
  if (e.created_at) bits.push(String(e.created_at).slice(0, 10));
  const chips = (e.relations || []).slice(0, 4)
    .map((r) => '<span class="graph-chip">' + _esc(r) + "</span>").join("");
  return (
    '<button type="button" class="graph-ebtn" data-id="' + _esc(e.id) + '">' +
      '<span class="graph-elabel">' + _esc(e.label || "(no label)") + "</span>" +
      (bits.length ? '<span class="graph-emeta">' + _esc(bits.join(" · ")) + "</span>" : "") +
      (chips ? '<span class="graph-chips">' + chips + "</span>" : "") +
    "</button>"
  );
}

function _bindEntityButtons(body) {
  body.querySelectorAll(".graph-ebtn").forEach((b) =>
    b.addEventListener("click", () => _openEntity(b.getAttribute("data-id"))));
}

async function _loadList(append) {
  const body = _root.querySelector(".graph-body");
  if (!append) {
    _offset = 0;
    body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  }
  const q = _query();
  try {
    const url = "/graph/entities?limit=" + _LIMIT + "&offset=" + _offset +
      (q ? "&q=" + encodeURIComponent(q) : "");
    const [list, stats] = await Promise.all([
      _get(url),
      append ? Promise.resolve(null) : _get("/graph/stats"),
    ]);
    if (list.ok === false) {
      body.innerHTML = '<div class="sysdiag-err">' + _esc(list.error || "graph unavailable") + "</div>";
      return;
    }
    const entities = list.entities || [];
    _matched = list.matched || 0;
    const cnt = _root.querySelector(".graph-count");
    if (cnt) cnt.textContent = q ? _matched + " of " + (list.total || 0) : (list.total || 0) + " entities";

    if (append) {
      const holder = body.querySelector(".graph-list");
      const more = body.querySelector(".graph-more");
      if (more) more.remove();
      if (holder) {
        holder.insertAdjacentHTML("beforeend", entities.map(_entityRow).join(""));
        _bindEntityButtons(holder);
      }
    } else {
      let html = _statsHtml(stats);
      if (!entities.length) {
        html += '<div class="sysdiag-muted">' +
          (q ? "no entity matches “" + _esc(q) + "”"
             : "no entities yet — the graph fills as Layla learns and links what you tell her") +
          "</div>";
      } else {
        html += '<div class="graph-list">' + entities.map(_entityRow).join("") + "</div>";
      }
      body.innerHTML = html;
      _bindEntityButtons(body);
    }

    _offset += entities.length;
    if (_offset < _matched) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "graph-more";
      btn.textContent = "load more (" + (_matched - _offset) + " left)";
      btn.addEventListener("click", () => _loadList(true));
      body.appendChild(btn);
    }
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

function _relSection(title, rows) {
  if (!rows.length) return "";
  return (
    '<div class="graph-sec-title">' + _esc(title) + " <span class=\"codex-n\">" + rows.length + "</span></div>" +
    rows.map((r) =>
      '<div class="graph-rel"><span class="graph-relname">' + _esc(r.relation || "linked") + "</span>" +
      '<button type="button" class="graph-chip" data-id="' + _esc(r.id) + '">' +
      _esc(r.label || ("#" + r.id)) + "</button></div>"
    ).join("")
  );
}

async function _openEntity(id) {
  if (id == null || id === "") return;
  const body = _root.querySelector(".graph-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const r = await fetch("/graph/entity/" + encodeURIComponent(id), { headers: { Accept: "application/json" } });
    if (r.status === 404) {
      body.innerHTML = '<button type="button" class="graph-back">‹ back</button>' +
        '<div class="sysdiag-muted">entity ' + _esc(id) + " is not in the graph</div>";
      body.querySelector(".graph-back").addEventListener("click", () => _loadList());
      return;
    }
    const d = await r.json();
    if (d.ok === false) {
      body.innerHTML = '<div class="sysdiag-err">' + _esc(d.error || "graph unavailable") + "</div>";
      return;
    }
    const ent = d.entity || {};
    const meta = ent.metadata || {};
    const metaRows = Object.keys(meta).slice(0, 12).map((k) =>
      '<div class="sysdiag-row"><span class="k">' + _esc(k) + '</span><span class="v">' +
      _esc(typeof meta[k] === "object" ? JSON.stringify(meta[k]) : meta[k]) + "</span></div>").join("");

    body.innerHTML =
      '<button type="button" class="graph-back">‹ back</button>' +
      '<div class="graph-dtitle">' + _esc(ent.label || "(no label)") + "</div>" +
      '<div class="sysdiag-card"><div class="sysdiag-card-title">entity</div><div class="sysdiag-body">' +
        '<div class="sysdiag-row"><span class="k">id</span><span class="v">' + _esc(ent.id) + "</span></div>" +
        (ent.created_at ? '<div class="sysdiag-row"><span class="k">learned</span><span class="v">' + _esc(ent.created_at) + "</span></div>" : "") +
        '<div class="sysdiag-row"><span class="k">relationships</span><span class="v">' + _esc(d.relationship_count) + "</span></div>" +
        metaRows +
      "</div></div>" +
      _relSection("outgoing", d.outgoing || []) +
      _relSection("incoming", d.incoming || []) +
      ((d.relationship_count || 0) === 0
        ? '<div class="sysdiag-muted">no relationships — nothing has been linked to this yet</div>'
        : "");

    body.querySelector(".graph-back").addEventListener("click", () => _loadList());
    body.querySelectorAll("button.graph-chip").forEach((b) =>
      b.addEventListener("click", () => _openEntity(b.getAttribute("data-id"))));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

export function openGraph() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  const q = _root.querySelector(".graph-q");
  if (q) { try { q.focus(); } catch (_) {} }
  _loadList();
}

export function closeGraph() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
  clearTimeout(_qTimer);
}

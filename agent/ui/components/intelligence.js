/**
 * components/intelligence.js — "Intelligence" overlay.
 *
 * Surfaces the flagship intelligence-tier backends that had NO UI door: mood (/mood),
 * goals (/goals), world model (/world), timeline (/timeline), decisions (/decisions), and
 * learned skills (/skills/learned). Read-only cards. Reuses the overlay shell + sysdiag tokens.
 * ⌘K → "Intelligence".
 */

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) {
  try { return await (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
  catch (_) { return null; }
}
function _rel(iso) {
  const t = Date.parse(String(iso || "").replace(" ", "T"));
  if (!t) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

function _card(title, sigil, bodyHtml) {
  return '<div style="border:1px solid var(--border);border-radius:5px;padding:9px 10px;background:var(--code-bg)">' +
    '<div style="font-size:0.62rem;text-transform:uppercase;letter-spacing:0.09em;color:var(--asp);margin-bottom:6px">' +
    _esc(sigil) + " " + _esc(title) + "</div>" + bodyHtml + "</div>";
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "intelligence";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Intelligence");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel" role="document" style="max-width:640px">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">✦</span>' +
        '<span class="sysdiag-title">intelligence</span>' +
        '<button type="button" class="sysdiag-refresh intel-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="intel-body" style="padding:10px;display:grid;grid-template-columns:1fr 1fr;gap:8px;max-height:70vh;overflow-y:auto"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeIntelligence(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeIntelligence(); } });
  _root.querySelector(".intel-refresh").addEventListener("click", _load);
}

async function _load() {
  const body = _root.querySelector(".intel-body");
  body.innerHTML = '<div class="sysdiag-muted" style="grid-column:1/-1">loading…</div>';
  const [mood, goals, world, timeline, decisions, skills] = await Promise.all([
    _get("/mood"), _get("/goals"), _get("/world"), _get("/timeline"), _get("/decisions"), _get("/skills/learned"),
  ]);
  const cards = [];

  // Mood
  if (mood) {
    cards.push(_card("Mood", "◎",
      '<div style="font-size:0.8rem;color:var(--text)">' + _esc(mood.label || "steady") + "</div>" +
      '<div style="font-size:0.62rem;color:var(--text-dim);margin-top:3px">valence ' + _esc((mood.valence || 0).toFixed ? mood.valence.toFixed(2) : mood.valence) +
      " · energy " + _esc((mood.energy || 0).toFixed ? mood.energy.toFixed(2) : mood.energy) + "</div>"));
  }

  // Goals
  if (goals) {
    const gs = goals.goals || [];
    const c = goals.counts || {};
    const body2 = gs.length
      ? gs.slice(0, 5).map((g) => '<div style="margin-bottom:2px">• ' + _esc(g.goal || g.title || g.description || g.text || "") +
          (g.progress != null ? ' <span style="color:var(--text-dim)">(' + _esc(g.progress) + "%)</span>" : "") + "</div>").join("")
      : '<div class="sysdiag-muted">No active goals. Tell Layla what you\'re working toward.</div>';
    cards.push(_card("Goals", "⌖", '<div style="font-size:0.7rem;color:var(--text)">' + body2 + "</div>" +
      (c.total ? '<div style="font-size:0.6rem;color:var(--text-dim);margin-top:4px">' + _esc(c.on_track || 0) + " on track · " + _esc(c.stalled || 0) + " stalled</div>" : "")));
  }

  // World model
  if (world) {
    const cp = world.current_project || {};
    const idx = world.repo_index || {};
    const lines = [];
    if (cp.name) lines.push("Project: " + _esc(cp.name) + (cp.lifecycle_stage ? " [" + _esc(cp.lifecycle_stage) + "]" : ""));
    if (idx.files) lines.push(_esc(idx.files) + " files · " + _esc(idx.symbols || 0) + " symbols");
    if ((world.projects || []).length) lines.push(_esc(world.projects.length) + " known project(s)");
    cards.push(_card("World model", "⊛",
      '<div style="font-size:0.7rem;color:var(--text)">' + (lines.length ? lines.join("<br>") : '<span class="sysdiag-muted">No project set. Point Layla at a workspace.</span>') + "</div>"));
  }

  // Timeline
  if (timeline) {
    const ev = timeline.events || [];
    const body2 = ev.length
      ? ev.slice(0, 6).map((e) => '<div style="margin-bottom:3px"><span style="color:var(--asp-cassandra,var(--asp));font-size:0.6rem">' +
          _esc(_rel(e.timestamp || e.created_at)) + "</span> " + _esc(e.content || e.description || e.summary || "") + "</div>").join("")
      : '<div class="sysdiag-muted">Nothing yet — milestones and events show here as you work together.</div>';
    cards.push(_card("Timeline", "⧗", '<div style="font-size:0.68rem;color:var(--text)">' + body2 + "</div>"));
  }

  // Decisions
  if (decisions) {
    const ds = decisions.decisions || [];
    const body2 = ds.length
      ? ds.slice(0, 5).map((d) => '<div style="margin-bottom:2px">• ' + _esc(d.decision || d.title || d.summary || d.content || "") + "</div>").join("")
      : '<div class="sysdiag-muted">No recorded decisions yet.</div>';
    cards.push(_card("Decisions", "⚖", '<div style="font-size:0.68rem;color:var(--text)">' + body2 + "</div>"));
  }

  // Learned skills
  if (skills) {
    const sk = skills.skills || [];
    const body2 = sk.length
      ? sk.slice(0, 6).map((s) => '<div style="margin-bottom:2px">• ' + _esc(s.name || "") +
          (s.step_count ? ' <span style="color:var(--text-dim)">(' + _esc(s.step_count) + " steps)</span>" : "") + "</div>").join("")
      : '<div class="sysdiag-muted">Layla learns reusable skills from finished multi-step tasks — none yet.</div>';
    cards.push(_card("Learned skills", "⚔", '<div style="font-size:0.68rem;color:var(--text)">' + body2 + "</div>"));
  }

  body.innerHTML = cards.length ? cards.join("") : '<div class="sysdiag-muted" style="grid-column:1/-1">Nothing loaded.</div>';
}

export function openIntelligence() {
  _build();
  _root.hidden = false;
  _open = true;
  _load();
}

export function closeIntelligence() {
  if (_root) _root.hidden = true;
  _open = false;
}

export function toggleIntelligence() {
  if (_open) closeIntelligence(); else openIntelligence();
}

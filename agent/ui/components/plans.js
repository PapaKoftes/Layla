/**
 * components/plans.js — durable plans + projects (W2 BL-048).
 *
 * Surfaces the /plans and /projects backends that had no UI:
 *   • Plans tab — workspace-scoped plan lifecycle: create (goal), list, expand steps,
 *     approve (draft→approved), execute (approved→executing). Status badges.
 *   • Projects tab — list/create projects; picking one fills the workspace field.
 * Overlay shell + G1 tokens; relative fetches. ⌘K → "Plans & projects".
 */

let _root = null;
let _open = false;
let _tab = "plans";

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
async function _send(url, method, body) {
  return (await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })).json();
}

function _workspace() {
  const el = document.getElementById("workspace-path") || document.querySelector("[data-workspace-path]");
  return el ? (el.value || el.textContent || "").trim() : "";
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "plans";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Plans and projects");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel plans-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">◈</span>' +
        '<span class="sysdiag-title">plans &amp; projects</span>' +
        '<span class="plans-ws"></span>' +
        '<button type="button" class="sysdiag-refresh plans-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="plans-tabs">' +
        '<button type="button" class="plans-tab" data-tab="plans">plans</button>' +
        '<button type="button" class="plans-tab" data-tab="projects">projects</button>' +
      "</div>" +
      '<div class="plans-create"></div>' +
      '<div class="plans-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closePlans(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closePlans(); } });
  _root.querySelector(".plans-refresh").addEventListener("click", _render);
  _root.querySelectorAll(".plans-tab").forEach((b) =>
    b.addEventListener("click", () => { _tab = b.getAttribute("data-tab"); _render(); }));
}

const _PLAN_ST = { draft: "st-draft", approved: "st-ok", executing: "st-run", done: "st-done", failed: "st-fail" };

function _render() {
  const ws = _workspace();
  const wsEl = _root.querySelector(".plans-ws");
  if (wsEl) wsEl.textContent = ws ? "⌾ " + ws.split(/[\\/]/).pop() : "";
  _root.querySelectorAll(".plans-tab").forEach((b) =>
    b.classList.toggle("active", b.getAttribute("data-tab") === _tab));
  const create = _root.querySelector(".plans-create");
  if (_tab === "plans") {
    create.innerHTML = '<input type="text" class="plans-goal" placeholder="new plan goal…" />' +
      '<button type="button" class="plans-add setup-btn primary">plan it</button>';
    create.querySelector(".plans-add").addEventListener("click", _createPlan);
    create.querySelector(".plans-goal").addEventListener("keydown", (e) => { if (e.key === "Enter") _createPlan(); });
    _loadPlans();
  } else {
    create.innerHTML = '<input type="text" class="proj-name" placeholder="project name…" />' +
      '<button type="button" class="proj-add setup-btn primary">create</button>';
    create.querySelector(".proj-add").addEventListener("click", _createProject);
    create.querySelector(".proj-name").addEventListener("keydown", (e) => { if (e.key === "Enter") _createProject(); });
    _loadProjects();
  }
}

// ── Plans ──────────────────────────────────────────────────────────────────
async function _loadPlans() {
  const body = _root.querySelector(".plans-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const ws = _workspace();
    const q = ws ? "?workspace_root=" + encodeURIComponent(ws) : "";
    const d = await _get("/plans" + q);
    const plans = d.plans || [];
    if (!plans.length) { body.innerHTML = '<div class="sysdiag-muted">no plans' + (ws ? " for this workspace" : "") + " — set a goal above</div>"; return; }
    body.innerHTML = "";
    plans.forEach((p) => {
      const st = (p.status || "draft").toLowerCase();
      const steps = Array.isArray(p.steps) ? p.steps : [];
      const el = document.createElement("div");
      el.className = "plan-item";
      let actions = "";
      if (st === "draft") actions = '<button type="button" class="plan-act" data-act="approve" data-id="' + _esc(p.plan_id) + '">approve</button>';
      else if (st === "approved") actions = '<button type="button" class="plan-act plan-exec" data-act="execute" data-id="' + _esc(p.plan_id) + '">execute</button>';
      el.innerHTML =
        '<div class="plan-head"><span class="plan-goal">' + _esc(p.goal || p.plan_id) + "</span>" +
        '<span class="plan-status ' + (_PLAN_ST[st] || "") + '">' + _esc(st) + "</span></div>" +
        '<div class="plan-sub"><button type="button" class="plan-toggle">' + steps.length + " steps ▾</button>" + actions + "</div>" +
        '<ol class="plan-steps" hidden>' + steps.map((s) =>
          "<li>" + _esc(s.title || s.description || s.text || s.action || JSON.stringify(s)) + "</li>").join("") + "</ol>";
      body.appendChild(el);
      el.querySelector(".plan-toggle").addEventListener("click", () => {
        const ol = el.querySelector(".plan-steps");
        ol.hidden = !ol.hidden;
      });
      const act = el.querySelector(".plan-act");
      if (act) act.addEventListener("click", () => _planAction(act.getAttribute("data-id"), act.getAttribute("data-act")));
    });
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _createPlan() {
  const inp = _root.querySelector(".plans-goal");
  const goal = (inp.value || "").trim();
  if (!goal) return;
  inp.value = "";
  const body = _root.querySelector(".plans-body");
  body.innerHTML = '<div class="sysdiag-muted">planning… (the planner drafts steps)</div>';
  try { await _send("/plans", "POST", { goal, workspace_root: _workspace() }); } catch (_) {}
  _loadPlans();
}

async function _planAction(id, act) {
  if (!id) return;
  try { await _send("/plans/" + encodeURIComponent(id) + "/" + act, "POST", {}); if (window.showToast) window.showToast("Plan " + act + "d"); } catch (_) {}
  _loadPlans();
}

// ── Projects ───────────────────────────────────────────────────────────────
async function _loadProjects() {
  const body = _root.querySelector(".plans-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/projects");
    const projs = d.projects || [];
    if (!projs.length) { body.innerHTML = '<div class="sysdiag-muted">no projects — create one above</div>'; return; }
    body.innerHTML = '<div class="proj-list">' + projs.map((p) =>
      '<button type="button" class="proj-item" data-ws="' + _esc(p.workspace_root || "") + '">' +
      '<span class="proj-pname">' + _esc(p.name || p.id) + "</span>" +
      (p.workspace_root ? '<span class="proj-pws">' + _esc(p.workspace_root) + "</span>" : "") + "</button>"
    ).join("") + "</div>";
    body.querySelectorAll(".proj-item").forEach((b) => b.addEventListener("click", () => {
      const ws = b.getAttribute("data-ws");
      const el = document.getElementById("workspace-path");
      if (el && ws) { el.value = ws; el.dispatchEvent(new Event("change", { bubbles: true })); if (window.showToast) window.showToast("Workspace set"); }
      _tab = "plans"; _render();
    }));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _createProject() {
  const inp = _root.querySelector(".proj-name");
  const name = (inp.value || "").trim();
  if (!name) return;
  inp.value = "";
  try { await _send("/projects", "POST", { name, workspace_root: _workspace() }); } catch (_) {}
  _loadProjects();
}

export function openPlans() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _render();
}

export function closePlans() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

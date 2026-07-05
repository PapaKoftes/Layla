/**
 * components/macros.js — workflow recorder & macro engine (BL-231).
 *
 * Browse saved macros (recorded tool sequences), inspect their steps, fill any
 * {{params}}, and replay them in one click via /macros. Overlay shell + G1 tokens.
 * ⌘K → "Macros / workflows".
 */

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }
async function _send(method, url, body) {
  return (await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })).json();
}

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "macros";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Macros and workflows");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel mkt-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">⟳</span>' +
        '<span class="sysdiag-title">macros / workflows</span>' +
        '<button type="button" class="sysdiag-refresh mac-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="mac-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeMacros(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeMacros(); } });
  _root.querySelector(".mac-refresh").addEventListener("click", _load);
}

async function _load() {
  const body = _root.querySelector(".mac-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/macros");
    const macros = d.macros || [];
    if (!macros.length) {
      body.innerHTML = '<div class="sysdiag-muted">no macros yet — save a workflow from a finished run to replay it later.</div>';
      return;
    }
    body.innerHTML = macros.map((m) => {
      const steps = (m.steps || []).map((s) => _esc(s.tool)).join(" → ");
      const runs = m.run_count ? '<span class="mac-runs">' + m.run_count + "×</span>" : "";
      const params = (m.params || []).map((p) =>
        '<label class="mac-param"><span>' + _esc(p) + '</span>' +
        '<input type="text" data-param="' + _esc(p) + '" placeholder="' + _esc(p) + '"></label>'
      ).join("");
      return '<div class="mac-item" data-name="' + _esc(m.name) + '">' +
        '<div class="mac-head"><span class="mac-name">' + _esc(m.name) + "</span>" + runs +
          '<button type="button" class="mac-run setup-btn" data-name="' + _esc(m.name) + '">▶ replay</button>' +
          '<button type="button" class="mac-del" data-name="' + _esc(m.name) + '" title="delete">✕</button>' +
        "</div>" +
        (m.description ? '<div class="mac-desc">' + _esc(m.description) + "</div>" : "") +
        '<div class="mac-steps">' + steps + "</div>" +
        (params ? '<div class="mac-params">' + params + "</div>" : "") +
        '<div class="mac-out" hidden></div>' +
      "</div>";
    }).join("");
    body.querySelectorAll(".mac-run").forEach((b) => b.addEventListener("click", () => _replay(b)));
    body.querySelectorAll(".mac-del").forEach((b) => b.addEventListener("click", () => _del(b)));
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

async function _replay(btn) {
  const name = btn.getAttribute("data-name");
  const item = btn.closest(".mac-item");
  const out = item.querySelector(".mac-out");
  const params = {};
  item.querySelectorAll("[data-param]").forEach((i) => { params[i.getAttribute("data-param")] = i.value; });
  btn.disabled = true;
  btn.textContent = "running…";
  out.hidden = false;
  out.innerHTML = '<span class="sysdiag-muted">replaying…</span>';
  try {
    const d = await _send("POST", "/macros/" + encodeURIComponent(name) + "/replay", { params, confirm: true });
    const rows = (d.results || []).map((r) =>
      '<div class="mac-res ' + (r.ok ? "is-ok" : "is-err") + '">' +
      (r.ok ? "✓" : "✗") + " " + _esc(r.tool) + (r.error ? " — " + _esc(r.error) : "") + "</div>"
    ).join("");
    out.innerHTML = '<div class="mac-res-hd">' + (d.ok ? "completed" : "failed") + " · " + (d.ran || 0) + " steps</div>" + rows;
  } catch (e) {
    out.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ replay";
  }
}

async function _del(btn) {
  const name = btn.getAttribute("data-name");
  if (!window.confirm("Delete macro “" + name + "”?")) return;
  try {
    await _send("DELETE", "/macros/" + encodeURIComponent(name));
    _load();
  } catch (e) { /* keep list as-is */ }
}

export function openMacros() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _load();
}

export function closeMacros() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

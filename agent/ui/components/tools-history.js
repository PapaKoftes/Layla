/**
 * components/tools-history.js — tool-call history & health (W2 BL-051).
 *
 * Surfaces /tools/analysis (aggregated per-tool success rate + latency) that had no UI.
 * Read-only dashboard. Reuses the overlay shell + G1 tokens; relative fetch (auth via the
 * patched fetch). ⌘K → "Tool history".
 */

let _root = null;
let _open = false;

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}
async function _get(url) { return (await fetch(url, { headers: { Accept: "application/json" } })).json(); }

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "toolshist";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Tool history");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel toolshist-panel" role="document">' +
      '<div class="cmdp-search-row"><span class="cmdp-search-icon" aria-hidden="true">⛭</span>' +
        '<span class="sysdiag-title">tool history</span>' +
        '<button type="button" class="sysdiag-refresh toolshist-refresh">refresh</button>' +
        '<kbd class="cmdp-esc">esc</kbd></div>' +
      '<div class="toolshist-body"></div>' +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("mousedown", (e) => { if (e.target === _root) closeToolsHistory(); });
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeToolsHistory(); } });
  _root.querySelector(".toolshist-refresh").addEventListener("click", _load);
}

function _pct(x) { return Math.round((x || 0) * 100) + "%"; }

async function _load() {
  const body = _root.querySelector(".toolshist-body");
  body.innerHTML = '<div class="sysdiag-muted">loading…</div>';
  try {
    const d = await _get("/tools/analysis?days=30");
    if (d.ok === false) throw new Error(d.error || "failed");
    const s = d.summary || {};
    const tools = d.tools || [];
    let html =
      '<div class="toolshist-summary">' +
        (s.total_calls || 0) + " calls · " + _pct(s.overall_success_rate) + " ok · " + (s.distinct_tools || 0) + " tools · " + (d.days || 30) + "d" +
      "</div>";
    if (!tools.length) {
      html += '<div class="sysdiag-muted">no tool calls recorded yet</div>';
    } else {
      html += '<div class="toolshist-table"><div class="toolshist-row toolshist-th"><span>tool</span><span>calls</span><span>ok</span><span>avg</span></div>' +
        tools.map((t) => {
          const rate = t.success_rate || 0;
          const cls = rate >= 0.9 ? "ok" : rate >= 0.6 ? "warn" : "bad";
          return '<div class="toolshist-row"><span class="toolshist-name">' + _esc(t.tool_name) + "</span>" +
            "<span>" + (t.calls || 0) + "</span>" +
            '<span class="toolshist-rate toolshist-' + cls + '">' + _pct(rate) + "</span>" +
            "<span>" + Math.round(t.avg_duration_ms || 0) + "ms</span></div>";
        }).join("") + "</div>";
    }
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<div class="sysdiag-err">error — ' + _esc(e.message || e) + "</div>";
  }
}

export function openToolsHistory() {
  _build();
  if (_open) return;
  _open = true;
  _root.hidden = false;
  _load();
}

export function closeToolsHistory() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

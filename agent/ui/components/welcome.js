/**
 * components/welcome.js — first-run welcome + honesty card (G5 / BL-091).
 *
 * Fuses the front of the onboarding into one linear flow: a warm welcome and Layla's core
 * promise (local-first, honest, your data stays yours) → hands off to the profile wizard
 * (which does features/model/workspace) → the app. Shown once on first run (localStorage),
 * and reachable any time via ⌘K → "Welcome / about". Overlay shell + G1 tokens.
 */

let _root = null;
let _open = false;
let _step = 0;

const _CARDS = [
  {
    icon: "∴",
    title: "welcome to layla",
    body: "A local-first companion that reads and writes only inside your workspace, thinks in the open, " +
      "and grows a memory of how you work. She runs on your machine — no account, no cloud required.",
  },
  {
    icon: "♥",
    title: "the promise",
    body: "Honesty over flattery — she tells you when she's unsure. Your data stays yours: memory lives in a " +
      "local database you own, and file changes + commands stay " +
      "behind approval gates. Revisit VALUES.md from Help any time.",
  },
];

function _build() {
  if (_root) return;
  _root = document.createElement("div");
  _root.id = "welcome";
  _root.className = "cmdp-backdrop sysdiag-backdrop";
  _root.setAttribute("role", "dialog");
  _root.setAttribute("aria-modal", "true");
  _root.setAttribute("aria-label", "Welcome");
  _root.hidden = true;
  _root.innerHTML =
    '<div class="cmdp-panel sysdiag-panel welcome-panel" role="document">' +
      '<div class="welcome-body"></div>' +
      '<div class="welcome-foot">' +
        '<span class="welcome-dots"></span>' +
        '<button type="button" class="welcome-skip">skip</button>' +
        '<button type="button" class="welcome-next setup-btn primary">next</button>' +
      "</div>" +
    "</div>";
  document.body.appendChild(_root);
  _root.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); _finish(false); } });
  _root.querySelector(".welcome-skip").addEventListener("click", () => _finish(false));
  _root.querySelector(".welcome-next").addEventListener("click", _onNext);
}

function _esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }

function _render() {
  const c = _CARDS[_step];
  _root.querySelector(".welcome-body").innerHTML =
    '<div class="welcome-icon" aria-hidden="true">' + _esc(c.icon) + "</div>" +
    '<div class="welcome-title">' + _esc(c.title) + "</div>" +
    '<div class="welcome-text">' + _esc(c.body) + "</div>";
  _root.querySelector(".welcome-dots").innerHTML = _CARDS.map((_, i) =>
    '<span class="welcome-dot' + (i === _step ? " on" : "") + '"></span>').join("");
  _root.querySelector(".welcome-next").textContent = _step >= _CARDS.length - 1 ? "set me up →" : "next";
}

function _onNext() {
  if (_step < _CARDS.length - 1) { _step++; _render(); return; }
  _finish(true);
}

function _finish(goSetup) {
  try { localStorage.setItem("layla_welcome_v1_done", "1"); } catch (_) {}
  closeWelcome();
  // Hand off to the profile wizard (features/model/workspace) to continue the flow.
  if (goSetup && typeof window.openSetupProfiles === "function") {
    try { window.openSetupProfiles(); } catch (_) {}
  } else {
    try { window.dispatchEvent(new CustomEvent("layla:welcome-closed", { detail: { goSetup } })); } catch (_) {}
  }
}

export function openWelcome() {
  _build();
  if (_open) return;
  _open = true;
  _step = 0;
  _root.hidden = false;
  _render();
}

export function closeWelcome() {
  if (!_root || !_open) return;
  _open = false;
  _root.hidden = true;
}

/** First-run gate: show the welcome once, before anything else. Returns true if shown. */
export function maybeShowWelcome() {
  try { if (localStorage.getItem("layla_welcome_v1_done") === "1") return false; } catch (_) {}
  openWelcome();
  return true;
}

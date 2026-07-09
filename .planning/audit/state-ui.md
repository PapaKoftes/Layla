# Layla Front-End State Audit — Actual Reachable UI

**Scope:** `agent/ui/` — vanilla-JS ES modules. Entry point `agent/ui/main.js` (one `<script type="module">`), shell `agent/ui/index.html` (1330 lines), 6 core modules, 51 component modules.

**Method:** Read `index.html` fully + `main.js` fully; diffed all 51 components against `main.js` imports; traced every nav/tab/button `data-action` to its handler; extracted backend endpoints per component.

---

## TL;DR

- **Nothing is dead at the module level.** All 51 components in `ui/components/*.js` are imported and initialized by `main.js`. There is no unimported/orphaned JS file.
- **The surfacing gap is real and large.** The app has two *visible* navigation systems that expose only ~9 surfaces. A **third** navigation — the ⌘K command palette — is the ONLY way to reach ~24 feature panels (missions, journal, debate, codex, kb, plans, verify, tutor, macros, marketplace, improvements, tools-history, sync, agent-tasks, intake-quiz, custom-aspect, german, welcome, self-test, system-diagnostics, setup-profiles, approvals).
- **The ⌘K palette has no discoverable affordance.** No button, no header icon, no hint. The only two Ctrl+K hints in the entire UI both say "**Clear input**" (`index.html:430`, `:1170`), which is the *opposite* binding.
- **Ctrl+K binding conflict.** `bootstrap.js:264` (capture-phase, document-level) opens the palette; `input.js:116` (input-level) clears the input. The capture-phase listener wins, so the documented "Clear input" shortcut is effectively overridden while the input is focused.

---

## Visible navigation (what a user actually sees & can click)

Two surfaces render the primary nav, both driving the **right-panel** (`#layla-right-panel`, slide-out overlay):

### A. Left sidebar nav (`.sidebar-nav`, index.html:293-300)
| Button | Action | Opens |
|---|---|---|
| ◈ Dashboard | `openOverlayPanel status` | right-panel → Dashboard tab |
| ⚙ Settings | `openOverlayPanel prefs` | right-panel → Settings tab |
| ◆ Models | `openModelsPanel` | Models & Kits modal (`#models-overlay`) |
| ▤ Library | `openOverlayPanel workspace` | right-panel → Library tab |
| ⌕ Research | `openOverlayPanel research` | right-panel → Research tab |
| ⬡ Artifacts | `openOverlayPanel artifacts` | right-panel → Artifacts tab |

### B. Right-panel tab strip (`.rcp-tabs`, index.html:442-448)
Dashboard · Settings · Library · Research · Artifacts (5 tabs).

### C. Other always-visible affordances
- **Aspect roster** (left sidebar `.sidebar-voices`): 6 aspect buttons (Morrigan/Nyx/Echo/Eris/Cassandra/Lilith) → `aspect.setAspect`.
- **Maturity card** + **dashboard cards** (governor/maturity/facts/cluster/uptime) → jump into Dashboard/Growth/Library.
- **Header ⋮ overflow menu**: export chat, system export, memory bundle, retry, clear, working notes, **Character Lab**, Terminal (CLI help), compact sidebar, context visualizer, shortcuts.
- **Topbar approvals badge** (`#topbar-approvals`) → `openApprovals`, but `display:none` until pending approvals exist.

---

## Surface → Component → Backend map

| Visible surface | Tab/entry | Component(s) | Backend endpoints |
|---|---|---|---|
| **Dashboard** | rcp `status` | `panels.js`, `growth.js`, `cluster.js`, `settings-full.js` (health), `workspace.js` (exec trace) | `/health`, `/debug/state`, `/debug/tasks`, `/api/growth/stats`, cluster status endpoints |
| **Settings** | rcp `prefs` | `settings-full.js`, `voice.js`, `perf.js`, `obsidian.js`, `pairing.js`, `research.js` | `/settings`, `/settings/optional_features`, `/settings/install_feature`, `/settings/git_undo_checkpoint`, `/codex/user`, obsidian + pairing endpoints |
| **Library** | rcp `workspace` (6 subtabs: Models/Awareness/Knowledge/Study/Memory/Plugins) | `workspace.js`, `memory.js`, `models.js` (platform), codex/skills in settings-full | `/memory/browse`, `/memory/{id}`, `/memory/import`, `/memory/elasticsearch/search`, workspace awareness, project_memory, skills, plans |
| **Research** | rcp `research` | `research.js`, `autonomous.js` | `/autonomous/run`, `/agent/tasks/<id>`, research mission endpoints |
| **Artifacts** | rcp `artifacts` | `artifacts.js` | client-side scan (extracts code blocks from responses) |
| **Models & Kits** | modal (sidebar ◆ + palette) | `models.js` | model catalog / HF download / switch-active endpoints |
| **Character Lab** | header ⋮ + palette | `character-creator.js` | `/aspects`, `/aspects/…`, `/character…` |
| **Chat rail** | left column (always) | `conversations.js`, `sidebar.js` (scroll helper), `chat-render.js`, `app.js` (send), `input.js` | `/conversations`, `/conversations/…`, `/projects` |
| Chat send/stream core | main area | `app.js`, `chat-render.js`, `voice.js`, `search.js` | chat/stream + `/compact` + global search |

`growth`/`cluster` have standalone `<section data-rcp="growth|cluster">` blocks that are `display:none`; `bootstrap.js:183` `_rcpAliases = { growth:'status', cluster:'status' }` remaps them into the **Dashboard** tab, where their content was merged. So they ARE reachable (via Dashboard), just not as their own tab.

---

## Component reachability table (all 51)

Legend: **Nav** = reachable from a visible button/tab. **Palette-only** = reachable ONLY via ⌘K. **Helper** = infrastructure, no standalone surface. **Auto** = shown automatically (first-run/streaming), not user-navigated.

| Component | Reachable? | Surface | Notes |
|---|---|---|---|
| app.js | Helper | (chat core) | send/compact/cancel orchestrator |
| chat-render.js | Helper | (chat core) | renders messages, retry, compose panel |
| input.js | Helper | (chat core) | keydown, theme, panel toggles, file drop |
| bootstrap.js | Helper | (nav plumbing) | `showMainPanel`, ⌘K binding, tab routing |
| aspect.js | **Nav** | left sidebar aspect roster + palette | 6 aspects = primary persona nav; drives ASPECTS roster |
| sidebar.js | Helper | (chat rail) | only `scrollActiveConversationIntoView` |
| conversations.js | **Nav** | chat rail (always visible) | new chat, rail, projects |
| settings-full.js | **Nav** | Settings tab + modal | huge; also health/codex/features/import |
| memory.js | **Nav** | Library → Memory subtab | browse/import/subtabs |
| workspace.js | **Nav** | Library subtabs | awareness/knowledge/study/plans/skills |
| growth.js | **Nav** | Dashboard (merged) | growth stats + verify review |
| cluster.js | **Nav** | Dashboard (merged) | cluster enable/pair/status |
| research.js | **Nav** | Research tab | mission + autonomous investigation |
| autonomous.js | **Nav** | Research tab / Study | exec monitor panel |
| artifacts.js | **Nav** | Artifacts tab | code-block extraction |
| models.js | **Nav** | Models modal (sidebar ◆) | model manager |
| character-creator.js | **Nav** | header ⋮ + palette | Character Lab overlay |
| voice.js | **Nav** | Settings → Voice | TTS/mic + preview |
| perf.js | **Nav** | Settings → Performance | voice sliders, low-fx |
| obsidian.js | **Nav** | Settings → Integrations | vault sync |
| pairing.js | **Nav** | Settings → Network | mDNS discovery |
| search.js | **Nav** | header global search | conversations/learnings/code |
| plan-viz.js | Auto | Gantt overlay (opened programmatically) | `laylaCloseViz` wired; opened from plan links |
| command-palette.js | Helper | (the ⌘K palette itself) | no visible trigger |
| approvals.js | **Nav*** | topbar badge (hidden until pending) + palette | *badge is `display:none` normally |
| **missions.js** | **Palette-only** | ⌘K → Missions | `/missions` |
| **journal.js** | **Palette-only** | ⌘K → Journal | `/journal` |
| **debate.js** | **Palette-only** | ⌘K → Deliberate | `/debate`, `/debate/modes` (feature-gated `multi_agent`) |
| **codex.js** | **Palette-only** | ⌘K → Relationship codex | `/codex/proposals`, `/codex/relationship` |
| **kb.js** | **Palette-only** | ⌘K → Knowledge base | `/intelligence/kb/articles`, `/intelligence/kb/build/*` |
| **plans.js** | **Palette-only** | ⌘K → Plans & projects | plan CRUD/approve/execute |
| **verify.js** | **Palette-only** | ⌘K → Verify learnings | (also partly surfaced via Growth "Review pending" in growth.js) |
| **agent-tasks.js** | **Palette-only** | ⌘K → Background tasks | `/agent/tasks` |
| **improvements.js** | **Palette-only** | ⌘K → Improvements | self-improvement proposals |
| **tools-history.js** | **Palette-only** | ⌘K → Tool history & health | tool-call analytics |
| **sync.js** | **Palette-only** | ⌘K → Sync (feature-gated `remote`) | syncthing/devices |
| **marketplace.js** | **Palette-only** | ⌘K → Kit marketplace | kit install |
| **tutor.js** | **Palette-only** | ⌘K → Language tutor | `/language/{lang}/*` |
| **german.js** | **Palette-only** | ⌘K → German | `/language/…` (redundant w/ tutor) |
| **macros.js** | **Palette-only** | ⌘K → Macros / workflows | record/replay |
| **intake-quiz.js** | **Palette-only** + wizard | ⌘K + wizard step 3 | `/operator/quiz/stage/`, `/operator/quiz/submit` |
| **custom-aspect.js** | **Palette-only** | ⌘K → Create custom aspect | `/character/custom-aspects` |
| **system-diagnostics.js** | **Palette-only** | ⌘K → System diagnostics | metrics/cot/audit |
| **self-test.js** | **Palette-only** | ⌘K → Run self-test | install proof |
| **setup-profiles.js** | **Palette-only** + first-run | ⌘K → Set up / reconfigure | intent-driven setup |
| **welcome.js** | Auto + palette | first-run + ⌘K → Welcome | `maybeShowWelcome` |
| setup.js | Auto | first-run model download overlay | wizard step 1 |
| wizard.js | Auto | first-run wizard overlay | 6-step onboarding |
| onboarding.js | Auto | first-run onboarding overlay | tour |
| ui-phases.js | Helper | (LaylaUI class) | phase/config plumbing |
| sprites.js | Helper | aspect sprite field | decorative |

---

## Biggest surfacing gaps (ranked)

1. **~24 feature panels are ⌘K-palette-only with zero visible entry point.** A mouse-only user, or anyone who doesn't know the shortcut, can never reach Missions, Journal, Debate/Deliberation, Relationship Codex, Knowledge Base, Plans & Projects, Verify Learnings, Background Tasks, Improvements, Tool History, Sync, Marketplace, Language Tutor, German, Macros, Custom Aspect, System Diagnostics, Self-Test, or the reconfigure wizard.

2. **The command palette has no discoverable affordance.** No ⌘K/spotlight button in the header or nav. The keyboard-shortcuts sheet (`index.html:1154-1179`) lists Enter/Ctrl+K(clear)/Ctrl+R/Ctrl+//Ctrl+F/Escape but **never mentions the command palette**. So even a power user reading the help sheet won't learn it exists.

3. **Ctrl+K is double-bound and mis-documented.** `bootstrap.js:264` (capture) opens the palette; `input.js:116` clears the input; UI text (`:430`, `:1170`) advertises Ctrl+K as "Clear input." Users are told the wrong thing, and the clear-input handler is shadowed while typing.

4. **Feature duplication that dilutes navigation.** `german.js` (German-only) and `tutor.js` (generalized language tutor) are both separate palette entries hitting overlapping `/language/*` endpoints. Consolidating would reduce the palette's 40+ commands.

5. **`verify.js` is redundantly surfaced.** Reachable both as a palette command AND inline in the Growth section ("Review pending facts →", growth.js). The palette entry is likely the discoverable-elsewhere path most users never use.

6. **Approvals is effectively hidden.** The only always-considered surface (`#topbar-approvals`) is `display:none` until there are pending approvals; otherwise Approvals is palette-only. A user wanting to review session grants proactively has no visible route.

---

## Notes / caveats

- Right-panel is a single slide-out overlay; "tabs" swap `.rcp-page` sections. Library has 6 subtabs; Memory has 3 sub-subtabs (Browse/Search/Checkpoints).
- `growth`/`cluster` standalone sections remain in the DOM (`display:none`) as JS-compat aliases; content lives in Dashboard.
- All palette panels self-inject their own overlay DOM on first open (no static container needed in index.html), which is why they don't appear in the HTML shell.
- Feature-gating: palette commands tagged `feature:'remote'` (sync) and `feature:'multi_agent'` (debate) are filtered by `/setup/state` `enabled_features`; they may be hidden even from the palette depending on config.

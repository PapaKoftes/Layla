# Castilla Release — UI/UX Remediation + One-Click Installer Plan

> Status: DRAFT for review · Author: design+eng pass, 2026-07-07 · Precedes v1.0.0 tag.
> This is the "final sprint" plan agreed earlier: (A) fix every issue from the adversarial
> UI/UX + aesthetics audit in the way that best fits Layla's intent, and (B) ship a
> dead-simple installer that provisions **everything including Python** on Win/mac/Linux.
>
> Grounding: every file/line reference below was verified against the live app (preview
> @1440×900 and 375×812, computed-CSS + WCAG math) and two repo-wide source maps. Nothing
> here is generic advice — it's surgical.

---

## Part 0 — The framing decision: what "fits the intention"

Layla is **not** trying to be a neutral corporate tool. The `layla-rebuild.css` header states the
brand intent explicitly: *"near-black + refined crimson + violet … one bloodline: deep crimson soul
→ wine-rose CTA → violet … calm chrome."* The gothic/mythic identity (goddess "aspects", Cinzel
display, wine-rose on near-black, the "Maturity/Awakening" growth arc) is **deliberate**, and it's
what makes Layla feel like a *companion* rather than a form.

So the audit's core tension — "occult RPG dashboard vs. professional tool" — is **not** resolved by
stripping the identity. It's resolved by **disciplining the craft** so the identity reads as
*intentional and premium* instead of *busy and amateur*. Right now the problem isn't the soul; it's
that the execution (monospace-everything, 18 ad-hoc type sizes, flat weight, half-emoji icons,
contrast fails, a firehose sidebar) undermines the soul.

**Recommended direction — "Disciplined Dual-Tone":** keep the identity, but split the surface into
two registers:

- **Work canvas** (chat, code, settings forms, model setup): calm, legible, low-chroma, humanist
  sans body text, generous spacing. This is where the user *does the task* — it should get out of
  the way.
- **Companion chrome** (wordmark, aspect identity, empty-state hero, growth moments): keep the
  characterful wine-rose + Cinzel + mysticism, but as *accents and moments*, not as the texture of
  every label.

Everything in Part 1 is written to serve that direction. Three alternative directions and the exact
decision are listed in **§Decisions** at the end — this is the one call I need from you before
implementing, because it sets the target for every token.

---

## Part 1 — UI/UX + Visual Remediation

### Coverage matrix (every audit finding → phase)

| # | Audit finding | Phase |
|---|---|---|
| A1 | Monospace body everywhere | U1 |
| A2 | Cinzel + JetBrains Mono clash | U1 |
| A3 | No type scale / 18 rendered sizes / no html font-size | U1 |
| A4 | Flat weight (all 400) | U1 |
| A5 | Muddy palette (2 pinks, 2 reds, teal, purple) | U2 |
| A6 | Contrast fails (#a03335, #8b0000, #6f6180) | U2 |
| A7 | Icon mishmash (geometric + emoji) | U3 |
| A8 | Radius chaos (7 radii) | U4 |
| A9 | Density / no rhythm | U4, U5 |
| A10 | Theme fights task | Part 0 direction + all |
| A11 | Polish defects (truncation, `/setup/auto` label, ALL-CAPS mono, double empty state) | U5, U6, U7 |
| W1 | Onboarding silently enables remote access | U7 |
| W2 | Two empty states + default-open panel over composer | U5 |
| W3 | Settings ×3, panels ×2 (duplicate destinations) | U6 |
| W4 | Mythology naming overhead + no visible reason to switch | U6 + U9 |
| W5 | Sidebar firehose (~20 blocks) | U5 |
| W6 | Cryptic glyph-only affordances | U3 |
| W7 | Model-setup path under-served | U7 |
| W8 | Duplicate control surfaces (topbar + legacy header) | U6 |
| W9 | Low-legibility feedback/state | U5 |
| W10 | Mobile/responsive broken | U8 |
| + | External `fonts.gstatic.com` fallback (privacy) | U1 |
| + | Light-theme token gap (surfaces/semantic) — real bug | U2 |
| ★ | NEW: aspects — make real differentiation visible + finish backend wiring | U9 |

Phases U1→U8 are ordered by leverage: the token layers (U1–U4) are pure CSS and unlock the biggest
visual gain for the least risk; U5–U8 touch markup/JS and IA.

---

### U1 — Typography system (highest leverage; fixes A1–A4 + font privacy)

**Why first:** one choice — monospace for 88% of text — is most of why it "doesn't feel good."
Fixing type is pure token work and transforms the whole app.

**Approach — introduce a font-role token trio and a real scale:**

1. **Add a humanist UI sans, self-hosted** (offline-first, no CDN). Bundle a variable or 2-weight
   woff2 into `agent/ui/vendor/fonts/` and add `@font-face` rules to
   `agent/ui/vendor/css/fonts.css`. Recommended face: **Inter** or **IBM Plex Sans** (both OFL,
   render superbly at 13–15px, pair well with a mono + a display serif). Ship 400/500/600 weights.
2. **Define role tokens** in `layla-rebuild.css` `:root` (the winning block, lines 9–75):
   ```
   --font-ui:      'Inter', system-ui, sans-serif;   /* body, labels, buttons, forms */
   --font-mono:    'JetBrains Mono', monospace;        /* code, hashes, model ids, metrics */
   --font-display: 'Cinzel', serif;                    /* wordmark + aspect identity ONLY */
   ```
3. **Repoint the body font** in the *two* places that set it: `layla.css:103` and
   `layla-rebuild.css:81` → `font-family: var(--font-ui)`. Then sweep the ~84 literal
   `font-family:'JetBrains Mono'` declarations (31 in layla.css, 53 in rebuild): keep mono only for
   genuinely monospaced content (code blocks, `.pill`, model ids, numeric metrics); switch the rest
   to `var(--font-ui)`. Constrain Cinzel (`--font-display`) to the wordmark + `.aspect-badge`
   (consolidated rule already at `layla-rebuild.css:147-150`) and retire the ~19 ad-hoc Cinzel
   applications in `layla.css`.
4. **Fix the rem base + kill the fractional sizes:** add `html { font-size: 16px }` (currently there
   is **no** `html` font-size; base lives on `body` at 13px in `layla-rebuild.css:82`, and `em`
   nesting compounds → the 12.48/13.6px values I measured). Then set body to a real base
   (`15px`/`0.9375rem`) and enforce a **6-step scale** by repointing the ~340 ad-hoc `rem` font-size
   literals to the existing tokens (`--text-xs/-sm/-base/-lg/--heading`, defined
   `layla-rebuild.css:55-59`) — the token system *exists* but only a minority of rules use it.
   Target scale: `12 / 14 / 16 / 20 / 28 / 40px`.
5. **Restore weight contrast (A4):** today 58/66 runs are weight 400. With a real sans, use
   400 body / 500 labels / 600 headings so hierarchy comes from weight, not just size. Bump the
   dominant 9–12px body clusters up to 14–15px.
6. **Privacy:** delete the four `https://fonts.gstatic.com/...` fallback `src:` URLs in
   `fonts.css` (lines 7, 15, 23, 31). A "runs-on-your-machine" app must not reference an external
   font host. (Confirmed live: these are what produced the failed gstatic fetches in the network
   log.)

**Files:** `vendor/css/fonts.css`, `vendor/fonts/*` (add woff2), `css/layla-rebuild.css` (:root +
body + ~53 rules), `css/layla.css` (:103 + ~31 rules). **Risk:** low (CSS only, cascade
source-of-truth is known). **Verify:** preview_inspect the distinct rendered font-sizes drop from 18
→ ~6; body font-family = Inter; network shows zero gstatic requests.

---

### U2 — Color & contrast system (fixes A5, A6, light-theme bug)

**Consolidate to one bloodline + a neutral ramp, and pass AA everywhere.**

1. **Kill the off-palette hues.** The teal `#4ecdc4` is a foreign object — replace with a token.
   Occurrences: `layla.css:1055, 1058, 2955` and inline JS `core/compat.js:254`. Repoint to
   `--success` (`#3fae6b`, already defined) or `--accent-text` depending on semantics (model-OK
   badge → `--success`).
2. **Fix the three AA failures** (measured on `#0a0008`): 
   - `#8b0000` used as text at `layla-enhanced.css:440-441` (contrast **2.06**) → `var(--accent-text)`
     (6.26) or `var(--danger)` per meaning.
   - `--text-faint` `#6f6180` (contrast **3.64**, fails normal text) — it's fine for large/decorative
     but is used as body-ish text in the command palette (`layla-rebuild.css:496, 498, 505, 516,
     519, 520`). Lighten `--text-faint` to ~`#8578a0` (≈4.6:1) so it passes as a secondary text
     color, and keep `--text-dim` (`#a294b0`, 7.28) for primary secondary text.
   - Any brick-red heading (`#a03335`, 2.97) → `--accent-text`.
3. **Neutralize borders.** `--border:#320044` is a saturated *purple* competing with the wine
   accent (this is a big part of "muddy"). Shift borders to a desaturated near-neutral
   (`#2a2230`-ish) so color comes from the accent, not the hairlines. Token edit only
   (`layla-rebuild.css:16-17`).
4. **One accent, two roles** (already mostly true, make it strict): `--accent:#b11655` for *fills*
   only; `--accent-text:#e85d8a` for *text/links* only. Audit remaining `color: var(--accent)`
   usages (the earlier a11y pass caught many; command-palette fallbacks at
   `layla-rebuild.css:491, 514, 517` still hardcode `#b11655`).
5. **Fix the light-theme bug (found during research).** `body.theme-light` (`layla.css:84-95`) only
   overrides the *legacy* tokens; it never redefines the rebuild-only tokens (`--surface`,
   `--surface-2/-3`, `--text-faint`, `--success`, `--danger`), so **light mode currently renders on
   dark surfaces**. Add those overrides to the `theme-light` block. (This also future-proofs the
   "calm work canvas" direction if we later offer a light default.)

**Files:** `css/layla-rebuild.css` (:root), `css/layla.css` (theme-light + teal lines),
`css/layla-enhanced.css:440-441`, `core/compat.js:254`. **Risk:** low–medium (light theme needs a
visual pass). **Verify:** re-run the WCAG script — every text color ≥ 4.5 (or ≥ 3.0 for large);
toggle light theme and confirm surfaces actually lighten.

---

### U3 — Iconography unification (fixes A7, W6)

**One icon system, no cryptic glyphs.** Today icons are half hairline Unicode geometry
(`∴ ◈ ◆ ⬡ ◉ ⚔ ✦ ◎ ⌖ ⊛`) and half full-color emoji (`📚 🔬 🌙 📎 🎤`) — they read as two apps.

**Approach:** adopt a single **inline-SVG line-icon set** (Lucide/Feather family, MIT/ISC, ~1KB
each, themeable via `currentColor`). Rationale over an icon font: no extra font file, tints with our
tokens, crisp at any size, zero external calls.

- Create `agent/ui/components/icons.js` exporting `icon(name)` → inline SVG string (the missing
  abstraction — today there is **none**). 
- Replace glyphs at the source sites the map found: `index.html` (wordmark `∴` at 6/175/380; aspect
  buttons 268–289; panel-shortcuts 294–299; dash cards 303–336; topbar 360–364; composer 📎/🎤 at
  414/416), `components/aspect.js:28-44` (`ASPECT_SYMBOLS`), `components/chat-render.js:325-332`
  (empty-state tiles).
- **Keep exactly one intentional glyph:** the `∴` wordmark can stay as a *brand* mark (it's the one
  cryptic symbol that earns its keep as a logo) — everything functional becomes a clear line icon
  with a text label.
- Aspects: pair each with a *recognizable* icon (code, telescope, memory/clock, spark, gavel,
  shield) instead of `⚔✦◎⚡⌖⊛`, so the icon communicates the *function* even before you learn the
  name (ties into U6).

**Files:** new `components/icons.js`; edits in `index.html`, `aspect.js`, `chat-render.js`, + ~12
component templates that hardcode emoji (growth.js, welcome.js, research.js, voice.js, …). **Risk:**
medium (broad but mechanical; no logic change). **Verify:** snapshot shows consistent SVG icons; no
emoji in chrome; each control has icon+label.

---

### U4 — Shape, spacing & rhythm (fixes A8, A9)

- **Collapse the 7 radii → 3 tokens.** We already have `--radius-sm:6 / --radius:10 / --radius-lg:14`
  (`layla-rebuild.css:63`). Sweep hardcoded `border-radius` literals (2/3/4/12/999px) to these
  tokens; keep `999px` only for genuine pills (status chips). One corner language.
- **Enforce the spacing scale.** `--sp-1..7` (4/8/12/16/24/32/48) exists but is bypassed. Repoint
  ad-hoc paddings/margins in the sidebar and cards to the scale so there's a consistent vertical
  rhythm (the "cramped, no breathing room" finding). Give the composer more height (it's a thin 38px
  bar) and the chat column a comfortable max-width.

**Files:** `css/layla-rebuild.css`, `css/layla.css` (radius/padding literals). **Risk:** low.
**Verify:** distinct radii ≤ 3; spacing values snap to the scale.

---

### U5 — Landing state, empty states & sidebar density (fixes W2, W5, W9, A11)

This is the biggest *perceived* clutter win.

1. **One empty state, not two/three.** The map found **three** renderers: `#context-chip`
   ("No chat selected…", `index.html:366`), the static hero `#chat-empty`
   (`index.html:375-388`), and a *different* JS hero ("`∴ she is waiting`" + 8 tiles) in
   `components/chat-render.js:299` (`renderPromptTilesAndEmptyState`), triggered on new/clear
   (`conversations.js:127,436`, `input.js:337`). **Decision + unify:** pick the JS hero as the
   single source (it's the richer one), delete the static `#chat-empty` inner markup so it's a
   pure mount point, and demote `#context-chip` to only appear when a chat *is* selected (not as a
   competing empty message). Reconcile the wordmark/tagline copy to one voice.
2. **Right panel closed by default.** It's *not* opened by base CSS (`.rp-open` is added by JS:
   `main.js:228`, `input.js:287/303`, `bootstrap.js:229` `showMainPanel`). Change the startup path so
   the 520px control-center doesn't auto-open over the composer; open it only on explicit user action.
   Also make it *push* rather than *overlay* the composer at wide widths, or cap its width.
3. **De-densify the sidebar.** Today ~20 blocks compete (`index.html` `.sidebar` 234–339). Reorder by
   task-frequency and demote operator telemetry:
   - Primary: New chat + search + conversation list.
   - Secondary (collapsible): the 6 aspects (already a `<details>` at 265–291 — default it
     *collapsed* with the active aspect shown as a single chip).
   - Move the 5 status cards (`GOVERNOR/MATURITY/FACTS/CLUSTER/UPTIME`, `.sidebar-dashboard`
     302–338) and the Growth/XP card (`#maturity-card` 247–264) **out of the primary rail** into the
     Dashboard panel where they belong. Uptime/cluster are operator diagnostics, not companion
     surfaces — they shouldn't outrank "New chat."
4. **Legible state (W9):** replace bare `Loading…` with a skeleton/empty-list message; ensure the
   "thinking" and model-status signals are visually distinct from the uptime timer.

**Files:** `index.html` (sidebar + empty-state markup), `components/chat-render.js`,
`components/conversations.js`, `components/input.js`, `main.js`/`bootstrap.js` (rp-open startup),
CSS. **Risk:** medium (markup + a little JS wiring). **Verify:** first paint shows one empty state,
panel closed, composer full-width; sidebar shows ≤ ~8 primary items.

---

### U6 — Information architecture: dedupe nav + naming (fixes W3, W4, W8, A11)

1. **Collapse duplicate destinations.** Settings has **3** entry points (left `⚙ Settings`
   `index.html:293-300`, right `SETTINGS` tab, topbar `⚙` 354–365); Dashboard/Models/Library/
   Research/Artifacts each appear **twice** (left `.sidebar-nav` list *and* right-panel tabs). Pick
   **one** model: the right-panel tab strip is the canonical destination list; the left "Panel
   shortcuts" becomes either removed or a single "Panels" toggle. Keep exactly one Settings entry
   (topbar gear → opens the Settings tab). 
2. **Kill the duplicate control surface (W8).** The legacy `<header>` (`display:none`, preserves IDs)
   duplicates topbar controls and already broke e2e once. Plan its removal or make the topbar the
   sole owner of those IDs (documented migration, not a silent delete).
3. **Naming / mental model (W4).** Keep the goddess names as *identity* but lead with *function*.
   In the aspect UI show `Coding · Morrigan`, `Research · Nyx`, etc. (function first, name as flavor),
   both in the sidebar `<details>` (`index.html:265-291`) and the `ASPECTS` source
   (`aspect.js:28-44`). A first-time user should never have to learn "Morrigan = software
   engineering" to start coding. Rename the section header consistently ("Modes" or "Aspects" — pick
   one; today it's "VOICES" in the UI and "aspects" in code).

**Files:** `index.html`, `components/aspect.js`, panel/nav components. **Risk:** medium (IA change;
needs the design-direction sign-off). **Verify:** each destination reachable one obvious way; e2e
updated.

---

### U7 — Onboarding & model-setup path + remote-access safety (fixes W1, W7, A11)

1. **W1 (trust bug) — do not silently enable remote access.** During this very audit, completing the
   first-run wizard auto-`POST`ed `/setup/apply` and flipped `remote_enabled:true`, locking the local
   instance behind the auth gate. For a privacy product this must be an explicit, off-by-default,
   clearly-explained opt-in ("Expose Layla to your network / the internet?" with the security
   implications), never a side effect of finishing onboarding. Audit `setup/apply` +
   `run_first_time.py` so the default first run leaves `remote_enabled:false`.
2. **W7 — make "get a model running" a first-class step.** New users see `○ No model`, a topbar name
   truncated to `…Q4_K_M.g` (`core/compat.js:238-254`: `if (tail.length>28) tail=tail.slice(0,28)` —
   fix the truncation to keep the extension or ellipsize mid-string), and a raw endpoint label
   `/setup/auto` in the dashboard (A11 — relabel to human text like "Auto-configure"). Design a
   guided "Choose your model" onboarding step that uses the existing hardware-based
   `provision_model.py` / `recommend_kit` and the resumable downloader (`model_downloader.py`) with a
   real progress UI, so first-run → chatting is a paved path, not plumbing.

**Files:** `agent/install/run_first_time.py`, `agent/routers/settings.py` (`/setup/*`),
`core/compat.js` (truncation), `components/onboarding.js` / `wizard.js`, dashboard label in
`index.html`. **Risk:** medium (touches setup flow + security default — test carefully). **Verify:**
fresh profile → onboarding never enables remote; model-name renders whole; guided model download
works end-to-end.

---

### U8 — Responsive / mobile (fixes W10)

At 375px the sidebar defaults **open, `position:fixed`, 280px (75% of screen)**, the input is
squished to 197px *behind* it, the hamburger toggle renders **0×0**, and the topbar **wraps to 111px
(3 rows)**. Since we ship i18n/RTL and a remote-access mode, someone *will* open this on a phone.

**Approach:** proper mobile breakpoints — sidebar off-canvas by default with a working hamburger
(fix the 0×0 toggle), topbar collapses overflow controls into the `⋮` menu instead of wrapping, chat
+ composer take full width. This is CSS + a small JS toggle fix; the desktop layout is unaffected.

**Files:** `css/layla-rebuild.css` (media queries), the sidebar-toggle handler. **Risk:** low–medium.
**Verify:** preview_resize mobile — no horizontal overflow, sidebar off-canvas, hamburger works,
topbar one row, input full-width.

---

### U9 — Aspect differentiation: surface it + finish the wiring (fixes W4 depth; the NEW requirement)

**Key finding (backend map): aspects are already ~60% behaviorally distinct — the differentiation
just isn't visible, and the last 40% is defined-but-unwired.** Each aspect already injects, live on
every turn:
- a distinct **system prompt / voice contract** (`personalities/*.json` `systemPromptAddition`, 300 B–
  3 KB; Lilith also has an NSFW variant) — loaded at `orchestrator.py:74-127`, injected at
  `services/prompts/system_head_builder.py:470-494`;
- **reasoning-depth bias** (deep/light — Morrigan/Nyx/Cassandra deep, Echo/Eris/Lilith light) applied
  at `services/personality/aspect_behavior.py:107-143` via `run_setup.py:217-226`;
- **response-length bias** (concise/medium/thorough) injected at `system_head_builder.py:737-744`;
- **max-steps bias** (4–12), **refusal authority** (`can_refuse`/`will_refuse`,
  `orchestrator.py:468-472`), **decision bias** (`efficient/risk_averse/disruptive/honest/…`,
  `orchestrator.py:285-310`), and **aspect-scoped memory + knowledge retrieval**
  (`system_head_builder.py:441-450, 553-564`).

So "give each aspect a different system prompt" is **already done**. Two real gaps remain:

**U9a — Make the differentiation legible (higher value; this is where "surface more options" lands).**
Today the user sees six goddess names + a one-line description and has *no visible reason* to switch.
Design an aspect experience that exposes the character that already exists: per aspect show its
**domain** (primary/secondary from `expertise_domains`), **response length + reasoning depth**,
**refusal stance**, **tool bias**, and **voice** — as a compact "why switch to me" card in the
switcher and an aspect-detail view. Source the metadata from `personalities/*.json` (add a small
read-only `/aspects` endpoint, or extend the existing UI `ASPECTS` in `components/aspect.js:28-44`,
which already mirrors the names/symbols). This is a redesign surface (fits U3/U5/U6), not new backend.

**U9b — Finish the wiring so switching changes *more* (opt-in, no default drift).** Three defined-but-
unused mechanisms:
1. **Tool preferences** — `ASPECT_TOOL_PREFERENCES` boost/suppress (`aspect_behavior.py:217-251`) and
   `_ASPECT_TOOL_WEIGHT` (`orchestrator.py:492-499`) exist but aren't applied in tool selection. Wire
   them into the decision path (~100 lines) so e.g. Lilith suppresses `run_shell`/`write_file`, Nyx
   boosts research tools.
2. **Per-aspect sampling** — add an optional `sampling` block (temp/top_p) to the JSONs, read in
   `services/llm/llm_gateway.py run_completion` (~80 lines). No-op when unset.
3. **Per-aspect model routing** — infra is half-built (`llm_gateway.py` `_resolve_aspect_model`,
   `~1600-1650`); add an optional `preferred_model` field (~40 lines). No-op when unset.

Total U9b ≈ <500 lines across 5–10 files at named hook points; all opt-in so no existing behavior
shifts unless a JSON declares it. **Files:** `personalities/*.json`, `services/personality/
aspect_behavior.py`, `services/agent/llm_decision.py`, `services/llm/llm_gateway.py`, +
`components/aspect.js`/`index.html` for U9a. **Risk:** U9a low (UI); U9b medium (touches decision +
sampling — gate behind tests). **Verify:** switching aspect visibly changes domain/length/refusal in
the UI; with U9b, tool shortlist + sampling differ per aspect in logs.

### Ship notes (cross-cutting — apply to every UI phase)

- **Bump the service-worker cache version for the redesign release.** `sw.js` is stale-while-
  revalidate, so a changed asset reaches existing installs automatically on the *second* load (the
  first serves stale + refreshes in the background — this is exactly why the preview showed stale CSS
  until a forced refresh). For a big visual change you want it to land *at once*, not one load late:
  bump `CACHE` in `agent/ui/sw.js` (done for this branch: `layla-ui-v5` → `v6`) so the activate
  handler purges old caches immediately. Re-bump on the final redesign ship.
- Keep every change on `castilla-ui-redesign` until the direction review; token phases (U1–U4) are
  independently revertable CSS.

### UI sequencing & effort

```
U1 Typography ───┐ (pure CSS + font file; do first, biggest gain)
U2 Color/AA   ───┤ (pure CSS/token)      ← U1..U4 are low-risk token work,
U3 Icons      ───┤ (SVG set + sweep)        shippable independently, no logic change
U4 Shape/space───┘
U5 Landing/sidebar ─┐ (markup + light JS)
U6 IA/naming/dedupe ┤ (markup + JS; needs direction sign-off)
U7 Onboarding/model ┤ (setup flow + security default)
U8 Responsive       ┤ (CSS + toggle)
U9 Aspects surface  ┘ (U9a UI with the redesign; U9b backend wiring, opt-in)
```

Rough size: **U1–U4 ≈ 60% of the visual payoff for ~30% of the effort** and can go on a branch you
eyeball in the live preview before we touch any markup. U5–U8 are where IA decisions matter and
should follow the Part 0 direction call.

---

## Part 2 — One-Click Installer (installs Python + every requirement)

### The decision, up front

**Recommended: unify all three OSes on a `uv`-powered bootstrap, wrapped per-OS for one-click UX.**

Why `uv` and not "finish the existing embedded-Python Inno path":

| Concern | Existing (PyInstaller + embedded CPython 3.11.9 + Inno) | **uv bootstrap (recommended)** |
|---|---|---|
| Installs Python itself | Yes (bundles embed CPython) | **Yes** (`uv python install`, from python-build-standalone; no system Python, no admin) |
| Cross-platform | Windows only; mac/Linux are **stubs** | **One mechanism on Win/mac/Linux** (uv is a single static binary everywhere) |
| Compiler-free heavy deps | Yes (wheel index) | **Yes** — same prebuilt wheel indexes (`abetlen` llama-cpp CPU wheels + PyTorch CPU) |
| Fragility | Embedded-Python `._pth`/pip bootstrap is finicky; version drift (Py 3.11.9, llama-cpp==0.3.19 ≠ source ranges) | Low — uv resolves against the real `requirements`/extras; no embed hacks |
| Maintenance | 3 tools (PyInstaller spec + embed bundler + Inno) | 1 tool + a thin per-OS wrapper |
| Simplicity (your ask) | Multiple moving parts | **Simplest that also installs Python** |

`uv` (Astral, v0.11.26 / June 2026) is purpose-built for exactly this: a self-contained installer
needing **no pre-existing Python or package manager**, it installs Python from
`python-build-standalone`, creates the venv, and resolves deps — and `uv python install` can
pre-provision Python for offline use. Combined with Layla's already-solved compiler-free wheel story,
this collapses the "install Python + native deps + venv + app" problem into one fast, reliable tool
that works identically on every OS.

We **keep Inno Setup as the Windows GUI shell** (Start-menu entry, uninstaller, `%LOCALAPPDATA%\Layla`
data dir it already manages) but swap its guts from "embed CPython" to "run the uv bootstrap." We
**reuse** the existing `launcher/layla_launcher.py`, `provision_model.py`, and self-test — this is an
*evolution* of what's there, not a throwaway.

### Installer phases

**IP1 — The bootstrap engine (cross-platform core).** A single idempotent script per shell
(`install/bootstrap.ps1` for Windows, `install/bootstrap.sh` for mac/Linux) that:
1. Ensures `uv` is present (download the static binary to a local dir if missing — no admin, no
   prereqs; offline variant ships it alongside).
2. `uv python install 3.12` (matches the enforced `>=3.11,<3.13`; reconcile the embed's 3.11.9 →
   3.12).
3. `uv venv .venv`.
4. `uv pip install` the `[cpu,llm]` extras (or full per hardware) **with the existing index URLs**:
   `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu` (+ PyTorch CPU index),
   `--index-strategy unsafe-best-match`, `--only-binary llama-cpp-python`. This reproduces exactly
   what `fresh_install.ps1:83-86` and CI already do — no compiler needed.
5. Provision a model via the existing `provision_model.py` (`recommend_kit` hardware probe →
   ~259 MB SmolLM2-360M on tiny boxes, ~1.8 GB Qwen2.5-Coder-3B balanced) with a progress UI.
6. Run the deep self-test, seed `runtime_config.json` (with `remote_enabled:false` — ties to W1),
   drop a launcher/shortcut.

**IP2 — Windows one-click wrapper.** Keep `installer/layla.iss` (Inno) but point it at the bootstrap
instead of the embedded-Python bundler. Result: double-click `LaylaSetup.exe` → wizard → Start-menu
"Start Layla" + uninstaller. Retire/repurpose `bundle_embedded_python.ps1`. Fix the **README drift**:
Windows steps still point at the deprecated `install.ps1`/`INSTALL.bat` shims instead of the real
installer.

**IP3 — macOS one-click (greenfield → done cheaply).** A double-click `Install Layla.command` (and a
`curl -LsSf … | sh` one-liner) that runs `bootstrap.sh`. Replaces the `build_macos.sh` stub. Optional
later: a `.app`/`.dmg` and notarization, but the `.command` gives one-click today.

**IP4 — Linux one-click (greenfield → done cheaply).** `install.sh` one-liner + a `.desktop` launcher,
running the same `bootstrap.sh`. Replaces the `build_appimage.sh` stub. (AppImage/Flatpak optional
later.)

**IP5 — Model & offline strategy.** Default = post-install download (current design, keeps installer
small). Offer a second artifact **`Layla-Castilla-Offline`** that bundles: the `uv`-fetched Python,
a local wheelhouse (`uv pip download` → `--find-links ./wheels --offline`), and a default GGUF — for
air-gapped/no-internet installs. This reuses the same bootstrap with `--offline`.

**IP6 — Reconcile pins & docs.** Align the Python target (3.12) and `llama-cpp-python` version across
`pyproject.toml`, `requirements*.txt`, `requirements-lock.txt`, and the installer (today: source
`>=0.3.1,<0.4`, lock `==0.3.2`, embed `==0.3.19` — pick one tested pin). Fix README.

**IP7 — Release automation.** Extend `.github/workflows/release.yml` (already builds the Windows
installer on `v*` tags) to also build+publish the mac `.command` and Linux `install.sh` bundles +
`SHA256SUMS`. One tag → three one-click artifacts.

**IP8 — Verification matrix.** Clean-VM install test per OS from zero (no Python, no build tools):
Windows 11, macOS, Ubuntu → installer → app reaches `/ui` and answers a prompt. This is the
acceptance gate for "installs EVERY requirement including Python."

### Installer sequencing

```
IP1 bootstrap engine ──┬─► IP2 Windows (Inno → bootstrap)
                       ├─► IP3 macOS (.command)
                       └─► IP4 Linux (install.sh/.desktop)
IP5 model/offline ─────────► (variant of IP1)
IP6 pins+docs  ────────────► (prereq cleanup, do alongside IP1)
IP7 release automation ────► (after IP2–IP4 exist)
IP8 clean-VM verification ─► (acceptance gate)
```

---

## Decisions — LOCKED 2026-07-07

1. **Design direction → Disciplined Dual-Tone, but with a FULL-REDESIGN mandate.** Keep the
   gothic/wine-rose companion identity, but we are *not* limited to retinting the existing shell:
   where a from-scratch layout/IA/component is genuinely better, easier to use, or surfaces more
   options for the user, **rebuild it that way** rather than patch it. This upgrades U5–U8 from
   "tidy the current shell" to "design the right shell" (see §Redesign mandate below).
2. **Installer → uv-unified bootstrap.** Confirmed. Inno stays as the Windows GUI shell; its guts
   swap from embedded CPython to the uv bootstrap. mac/Linux get the same engine via `.command` /
   `install.sh`.
3. **Offline installer → NOT in v1.0.0.** Ship the simple online bootstrap now; the air-gapped
   `Layla-Castilla-Offline` bundle is a documented fast-follow (IP5 stays specced, deferred).
4. **Aspects → names-first identity + real functional differentiation.** Keep the goddess names as
   the primary identity (Morrigan, Nyx, Echo, Eris, Cassandra, Lilith); canonical label = **Aspects**.
   NEW REQUIREMENT: expand each aspect into a genuinely distinct behavior (per-aspect system
   prompt/persona, and where it fits, sampling + tool bias) so there's a real reason to switch —
   see new workstream **U9** below.

## Redesign mandate (how "full redesign" changes the approach)

Per decision #1, U5–U8 are no longer constrained to the current 3-pane shell. Deliverable before
implementing markup: **a concrete redesign proposal** (annotated layout + IA + component inventory),
reviewed in the live preview, covering at minimum —
- A reconsidered **information architecture**: one canonical place per destination (no settings ×3),
  a primary "work canvas," and a home for operator telemetry that isn't the main rail.
- A **layout** that may depart from today's sidebar+chat+520px-panel (e.g., collapsible rail, a
  command-first surface, panels as overlays not a permanent third column) — chosen for task-first use.
- Surfacing **more of Layla's power** where it currently hides (aspects with real differentiation,
  research/library/artifacts/memory) without recreating the firehose — progressive disclosure.
- Built on the U1–U4 token foundation so the new components inherit the disciplined system for free.

The token work (U1–U4) is still the correct first move: it's the design system every redesigned
component will consume, it's zero-logic-risk CSS, and it makes the redesign proposal concrete instead
of theoretical.

## Suggested first move

1. Ship **U1 (typography) + U2 (color/AA)** on a branch — pure token-layer CSS — so you see the
   single biggest quality jump live in the preview and we lock the palette/type system the redesign
   will build on.
2. In parallel, I produce the **redesign proposal** (IA + layout + component inventory) for your
   review before any markup rebuild.
3. Then U3→U9 + the installer track (IP1→IP8).

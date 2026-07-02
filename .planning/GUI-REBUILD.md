# Layla — GUI + Startup Rebuild Plan (2026-07-02)

A from-scratch redesign of the interface **and** the first-run experience. Goal:
**clean, minimal, streamlined, professional — with our soul.** Nothing is built from
this doc until you approve it; the mockups render the target so you can react to the
real thing, not prose.

## 5 design principles
1. **Calm, not busy.** One accent, one ornament, generous space. No neon glow walls, no
   glyph confetti, no status-chip row. The content (your conversation) is the hero.
2. **Soul through restraint.** The identity is the *near-black + a single refined
   crimson/violet accent + the aspect that re-themes it* — carried by color and one
   whisper-subtle damask, not by decoration everywhere.
3. **Professional defaults.** Readable UI type, real spacing scale, honest hierarchy,
   fast purposeful motion. It should feel like Linear/Claude-grade craft, dressed in Layla.
4. **The aspects ARE the navigation.** Switching personality is the primary gesture,
   front and center — that's the product, not a buried setting.
5. **Honest onboarding.** The startup tells the truth about your machine and proves it
   works before it says "ready."

## Audit — what's wrong today
**GUI**
- **Too busy:** per-aspect circuit/constellation background tiles + ascii doodle overlay +
  a big glowing spirit + multi-layer neon glows + a dense status-chip row. Reads "gamer HUD," not "professional."
- **All-mono type** (JetBrains Mono everywhere) → technical but low readability + not "clean."
- **Inconsistent density:** ad-hoc paddings/radii per component; no shared scale (the `--sp-*`
  tokens exist but are unused).
- **IA sprawl:** 197 tools + cluster + tribunal + gamification all competing for the surface.
- **~28 components themed independently** → drift.

**Startup**
- The 6-step wizard (hardware → model → workspace → character → voice) is functional but
  **dense and un-guided**; the BG3 character creator upfront is a lot before you've said hello.
- No **honesty card** (what this machine realistically does).
- No **visible proof** it works (the self-test exists but isn't surfaced) → "is it even working?"
- Onboarding interview is separate and easy to miss.

## The new design system
**Palette** (refined, professional, same soul)
```
--bg        #0a0710   near-black, faint warm-violet
--surface   #130f1a   rail / panels
--surface-2 #1b1526   cards, composer, elevated
--surface-3 #241d31   hover / active elevated
--border    #241d30   hairline
--border-2  #372c48   emphasis divider
--text      #ece7f3   /  --text-dim #9a8fa8  /  --text-faint #665d73
--accent    #c0395e   refined rose-crimson (primary CTA / active) — the soul color
--accent-2  #7d5bb8   violet (secondary)
per-aspect --asp:  morrigan #c0395e · nyx #7d5bb8 · echo #3f6fb0 · eris #b5763a · cassandra #2f8f86 · lilith #a33b52
--success #3fae6b · --danger #d0454e · --focus ring = accent @ 45%
```
**Type** — professional + soul, **offline-safe**
- `--font-display: 'Cinzel', serif` — the `∴ LAYLA` wordmark + a few headings ONLY.
- `--font-ui: system-ui, -apple-system, 'Segoe UI', Inter, sans-serif` — all UI text (readable, zero-weight, always present).
- `--font-mono: 'JetBrains Mono', monospace` — code, tokens, data.
- Scale 12 / 13 / 14 / 16 / 20 / 28; weights 400 / 500 / 600 only.

**Space** 4·8·12·16·24·32·48 · **Radius** 6 / 10 / 14 · **Motion** 120ms hover, 200ms panels, no glows.
**Ornament** the damask at **~4%**, only on empty states + the rail foot; a 2px accent hairline for active. That's the whole ornament budget.
**Icons** one consistent line-icon set (Tabler/Lucide-style), 18–20px, `currentColor`.

## Information architecture (new)
```
┌─ Aspect rail (64px) ──┬─ Conversations (280, collapsible) ─┬─ Main ────────────────┐
│  ⚔ Morrigan (active)  │  + New chat                        │  slim header:         │
│  ✦ Nyx                │  ─ Today                           │   title · aspect ·    │
│  ◎ Echo               │    · Fix the parser                │   system dot · … menu │
│  ⚡ Eris               │    · Spanish notes                 │                       │
│  ⌖ Cassandra          │  ─ Earlier                         │  ── messages ──       │
│  ⊛ Lilith             │    · …                              │  (calm, readable)     │
│  ─────                │                                    │                       │
│  ◉ Memory             │                                    │  ── composer ──       │
│  ◆ Models             │                                    │   [ ask Layla…    ↑ ] │
│  ⚙ Settings           │                                    │                       │
└───────────────────────┴────────────────────────────────────┴───────────────────────┘
                                              Right context panel (320, slide-in, off by default):
                                              sources/memory for the turn, or the open panel.
```
**Surfaces (kept):** Chat · Aspects · Memory/Knowledge · Models & Kits · Settings · Doctor.
**Cut to the wedge (Phase 3, parked behind flags):** cluster mesh, tribunal council, gamification-as-headline, the status-chip row (→ one **system dot** in the header that expands to governor/health/uptime).

## The screens (what gets built)
1. **Main / Chat** — the layout above; empty state = wordmark + one line + 3 suggested prompts.
2. **Aspect switch** — click a rail glyph → the accent + header retheme; a slim "now: Morrigan — the architect" confirmation. The full **aspect creator** lives in Settings, not the rail.
3. **Panels (Memory · Models & Kits · Settings · Doctor)** — one **card system**, opening in the right panel (or centered modal on narrow screens). Models & Kits keeps the #1 look you liked, in the new system.
4. **Composer** — single clean input, ⌘/Ctrl+K command palette, @file + attach, streaming.
5. **System dot** — governor/health/uptime in a small popover, not a chip row.

## The startup experience (new — calm, honest, 5 steps)
1. **Welcome** — full-screen: `∴ LAYLA`, "A private AI that's yours — runs on your machine, remembers what matters." → **Begin**.
2. **Your machine** (honesty card) — "16 GB · CPU. Here's what runs well for you: **Qwen2.5-Coder-3B** — fast, good for edits and chat. (Bigger models available if you have the room.)" Honest, no overpromise.
3. **Get the model** — one clean progress bar (resumable). If already present: "Found it. ✓".
4. **Your space** — pick a workspace folder (one field, with a sensible default).
5. **Ready — proof, not a promise** — runs the **self-test live**: `model loads ✓ · a real reply ✓ · memory ✓`, then **Start chatting**. Personality/voice = an *optional* "make it yours" you can do now or later (not forced).
Onboarding tips fold into the empty chat state (contextual), not a separate wizard.

## Build approach (from-scratch, low-risk)
- **Rebuild the design + structure from scratch; reuse the working plumbing.** New CSS
  architecture (tokens → primitives → components → screens), new layout HTML, new component
  library — but keep the proven **API layer, state bus, and endpoint wiring** (the backend
  contract is solid). This *is* a from-scratch UI, without throwing away 197 working integrations.
- **One stylesheet system** replaces layla.css/enhanced/polish: `tokens.css` → `base.css` →
  `components.css` → `screens.css`. Delete ad-hoc inline styles.
- **Framework?** Recommended: stay **vanilla ES modules** (already modular, zero build step,
  offline-trivial). Optional future: Svelte if the component count demands it — noted, not now.
- **Migration, phased & shippable each step:**
  - **G1 Design system** — tokens + primitives + icon set + the new shell (rail/list/main), empty state. *(the look is set)*
  - **G2 Chat** — messages, composer, streaming, command palette.
  - **G3 Panels** — the card system: Models & Kits, Memory, Settings, Doctor.
  - **G4 Aspects** — rail switching + retheme + the aspect creator in Settings.
  - **G5 Startup** — the 5-step calm onboarding + live self-test.
  - **G6 Responsive + a11y + motion polish → SIGN-OFF.**
- Each Gx is a reactable pass against the running app; `check_ui_symbols.py` + e2e-ui green per step.

## What you're approving
The **direction** (calm/professional/soul), the **design system** (palette/type/space/ornament),
the **IA** (aspect rail + conversations + chat + slide-in context; the cuts), and the **startup
flow**. On your yes, I build G1 first and show you — then G2…G6, one reactable pass each.

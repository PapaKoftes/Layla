# Dropped-in Claude ecosystem sources (local)

**Archives (repo root, not tracked unless you choose):**

| Archive | ~Size | Extracted under |
|--------|------:|-----------------|
| `claude-code-sourcemap-main.zip` | 16 MB | `integrations/claude-code-sourcemap-main/claude-code-sourcemap-main/` |
| `claw-code-main.zip` | 5 MB | `integrations/claw-code-main/claw-code-main/` |
| `openclaude-main.zip` | 10 MB | `integrations/openclaude-main/openclaude-main/` |

GitHub-style zips add a **nested folder** with the same name; the real project roots are the **inner** directories above.

**What each tree is (from upstream READMEs):**

1. **claude-code-sourcemap** — Claude Code research preview with extracted source maps (`cli.mjs`, `src/`, `vendor/`). Upstream notes a fork at anon-kode; treat as **reference / research** for behavior and tooling patterns.
2. **claw-code** — “Claw” harness / tools ecosystem (Rust + TS in this snapshot); `PARITY.md`, `CLAW.md` describe goals vs Claude Code.
3. **OpenClaude** — Claude-Code-like CLI with **OpenAI-compatible** providers (Bun/TS + some Python helpers: `ollama_provider.py`, `smart_router.py`).

**Layla integration rules (project):**

- Do not wire these into `agent/` until there is an explicit design: **facade module**, **config**, and **tests**.
- Prefer **subprocess / optional dependency** or **documented manual install** over copying huge `vendor/` trees into the main package.
- Keep **Layla** defaults: local GGUF, approval gates, `runtime_safety` config — any merged CLI must not bypass those without a deliberate operator choice.

**Recreate extracts** (from repo root):

```powershell
Expand-Archive -Path claude-code-sourcemap-main.zip -DestinationPath integrations/claude-code-sourcemap-main -Force
Expand-Archive -Path claw-code-main.zip -DestinationPath integrations/claw-code-main -Force
Expand-Archive -Path openclaude-main.zip -DestinationPath integrations/openclaude-main -Force
```

**Next step for a new chat:** @-mention the inner folder you want to port from, plus `AGENTS.md`, `ARCHITECTURE.md`, and this file.

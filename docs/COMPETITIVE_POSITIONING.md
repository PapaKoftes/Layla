# Competitive positioning (by category, not exhaustive)

**Purpose:** Directional framing for operators and contributors. This is **not** a benchmarked product catalog, a live API comparison, or legal/marketing claims.

**Evidence for Layla:** See [`FULL_TECHNICAL_AUDIT.md`](FULL_TECHNICAL_AUDIT.md), [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`PROJECT_BRAIN.md`](../PROJECT_BRAIN.md), and [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).

**Confidence in competitive rows:** roughly **0.55–0.65** (qualitative; no side-by-side benchmark runs in-repo).

---

## Category matrix (illustrative)

| Category | Examples (illustrative only) | Layla differentiator | Typical gap vs category leaders |
|----------|------------------------------|----------------------|----------------------------------|
| **Local GGUF agent** | Oobabooga chat, LM Studio + scripts | Full agent loop, large tool registry + count test, memory, approvals, Web UI | Less “drop-in chat”; heavier setup |
| **IDE-native coding agent** | Cursor, Copilot, Windsurf | Self-hosted, sandbox path policy, no subscription to vendor model | Weaker inline diff / IDE UX unless via MCP |
| **Cloud coding agents** | Managed “autonomous dev” products | Data stays local; operator owns model | No managed infra, no fleet scale |
| **Framework / AutoGPT-style** | LangGraph, CrewAI, AutoGPT forks | Opinionated product + approval + SQLite plans + UI | Less generic graph programming; fewer third-party “agent marketplace” integrations |
| **Research / RAG stacks** | PrivateGPT, AnythingLLM | Tight coupling to Layla tools + aspects + study | Less plug-and-play “upload PDF only” positioning |
| **Companion / character** | Hosted character chat products | Six aspects, Lilith gate, learnings, local | Commercial polish and mobile apps |

---

## Disclaimers

- **Named products** are examples only; capabilities change frequently.
- **Layla** is aimed at a **local operator**; do not read this matrix as “production SaaS at scale” positioning (see [`PRODUCTION_CONTRACT.md`](PRODUCTION_CONTRACT.md) and audit scope boundaries).
- Prefer **repo-evidenced** statements for engineering decisions; use this doc for **context**, not as a substitute for reading the code.

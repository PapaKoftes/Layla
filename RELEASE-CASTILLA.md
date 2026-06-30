# Release: **Castilla**

Layla as a **Spanish-first, private, local coding companion**, tuned for a modest laptop
(Intel i7-7700HQ, 16 GB RAM, 2 GB VRAM, ~26 GB free disk). Named for Castile — Castilian Spanish.

## What's in it
- **Bilingual ES/EN by default** — responds in **Spanish (Castellano)**, keeps code, identifiers
  and standard technical terms in English. Wired via `custom_system_prefix` (`--spanish`); appended
  to the system prompt in `services/prompts/system_head_builder.py`.
- **Right-sized model** — default **Qwen2.5-Coder-3B-Instruct Q4** (~2 GB, ~6–8 tok/s on a 2017 CPU;
  multilingual). **1.5B** floor for very tight disks; **7B** optional for max quality (~3 tok/s, 4.7 GB).
  Selected by the new `prefer="lite"` mode (targets ~3B) in `install/model_selector.recommend_kit`.
- **Disk-aware install** — `install/provision_model.py` detects free space and auto-downgrades to a
  lighter model when disk is tight (<12 GB free), so it never fills her drive.
- **One-command Spanish installer** — `install/castilla.ps1` (compiler-free: Python 3.12 → venv →
  CPU wheels → detect hardware → download model → configure Spanish). English path: `install/fresh_install.ps1 -Prefer lite -Spanish`.
- **Built on unified `master`** — the refactor (agent-loop decomposition, 19-package services,
  frontend modules, companion VISION) + this session (REQ-10/11/12 security, compiler-free memory
  fallback, hardware→kit recommender, benchmark, installer). **2143 tests green.**

## Install (for her)
- Español: `README-ES.md`
- English: `install/INSTALL.md`

```powershell
git clone https://github.com/PapaKoftes/Layla.git ; cd Layla
powershell -ExecutionPolicy Bypass -File install\castilla.ps1
```

## Honest notes
- Qwen2.5-Coder's Spanish is **good for conversation**, not native-grade. For native Spanish *chat*
  (non-coding), a general Spanish model can be added later as a second aspect.
- The i7-7700HQ is CPU-only for inference (2 GB VRAM can't hold a useful LLM); the 3B keeps it snappy.
- Connect to the main-PC Layla over a secure tunnel: `install/connect_tunnel.ps1` (auth-required-by-default).

## Provenance
Catalog: `qwen2.5-coder-3b-instruct-Q4_K_M`, `qwen2.5-coder-1.5b-instruct-Q4_K_M` added.
Hardware target confirmed from the operator's screenshot (2026-06-30).

## Update — low-end optimization + languages + personalities (2026-06-30)
- **Dynamic resource governor (low-end first).** Real keyboard/mouse detection drives three
  modes: **WHISPER** (you're using the laptop → Layla backs off: half the CPU cores, lowered
  OS priority, background work paused), **BREATHE** (lightly idle → moderate), **SPRINT**
  (idle → all cores, background research/initiative). New: `get_inference_threads` (the model
  itself throttles), live process-priority on mode change, and immediate back-off on an
  incoming chat. Wired into `llm_gateway` model load. Enabled by default (`resource_governor_enabled`).
  *So it never chokes the laptop in use, and gets the most out of the AI while idle.*
- **Language helper (optional).** A small **multilingual** model (Qwen2.5-1.5B, ~1GB) for
  translation/intent. Install with `-LanguageHelper` (or `provision_model.py --language-assist`).
- **Per-personality models.** Each aspect can provision its own domain model: morrigan→coding,
  nyx→reasoning, echo→general, eris/lilith→creative. `-Aspects nyx,echo` (or `--aspects`).
- **Verified Spanish:** the 3B coder loads in ~3s and runs **~9 tok/s**, answering in fluent
  Spanish with correct code (proof run 2026-06-30).

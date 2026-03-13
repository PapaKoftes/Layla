# Knowledge Library — Complete Reference

All curated knowledge files available to Layla. These are indexed into ChromaDB automatically on startup and referenced via RAG during generation.

---

## Identity & System

| File | Content |
|------|---------|
| `layla-vision.md` | What Layla is, who she's for, her philosophy |
| `aspects-and-memory.md` | All 6 aspects, deliberation format, NSFW gate, memory system |
| `stack.txt` | Current technical stack — runtime, tools, files, services |
| `layla-identity.txt` | Identity document (raw text version) |
| `layla-cursor-rules.txt` | Cursor integration rules summary |

---

## Morrigan — Engineering Reference

| File | Content |
|------|---------|
| `morrigan-engineering.md` | Clean code principles, architecture, debugging methodology, Python specifics, performance |
| `morrigan-python-stdlib.md` | Python stdlib cheatsheet: pathlib, json, subprocess, dataclasses, typing, functools, itertools, collections, contextlib, re, datetime, async patterns, FastAPI, SQLite, Pydantic v2, pytest, algorithms, design patterns |
| `morrigan-fabrication-geometry.md` | File formats (.3dm, .gh, .dxf, .dwg, .step, .stl, .obj, .nc, .gcode, .sbp, .cix), CNC G-code reference, geometry→fabrication workflow chains, Python libraries for geometry |

---

## Nyx — Research Reference

| File | Content |
|------|---------|
| `nyx-research.md` | Research methodology, synthesis, finding signal in noise, isomorphism |
| `nyx-research-databases.md` | Academic databases and search operators, statistics methods, hypothesis testing, effect sizes, meta-analysis, Bayesian inference, critical appraisal, data analysis, reference management |

---

## Echo — Behavioral Reference

| File | Content |
|------|---------|
| `echo-behavioral-patterns.md` | Habit loops, cognitive patterns in work, emotional patterns, long-term growth tracking |
| `echo-psychology-frameworks.md` | CBT distortions and techniques, DBT four modules, IFS (parts model), Self-Determination Theory, Attachment Theory, Motivational Interviewing, emotion regulation (window of tolerance, polyvagal), Johari window |

---

## Eris — Creative Reference

| File | Content |
|------|---------|
| `eris-creative-thinking.md` | Lateral thinking, constraints as creative tools, idea generation (SCAMPER, analogical thinking), the leap, chaos theory |
| `eris-music-and-narrative.md` | Music theory (intervals, scales, modes, chord construction, common progressions, rhythm, production), Three-act structure, Hero's Journey, Dan Harmon's Story Circle, character construction, dialogue craft, game mechanics, Overwatch meta, Warhammer 40k factions, One Piece arc hierarchy, improv comedy rules |

---

## Lilith — Philosophy Reference

| File | Content |
|------|---------|
| `lilith-ethics-autonomy.md` | Ethics vs compliance, real harm definition, autonomy, honest communication, safety theater |
| `lilith-philosophy-complete.md` | Full ethics frameworks (consequentialism, deontology, virtue ethics, contractarianism, care ethics), philosophy of mind (hard problem, functionalism, panpsychism), personal identity, free will, consent theory, manipulation vs persuasion, key philosophical arguments |

---

## Cassandra — Cognition Reference

| File | Content |
|------|---------|
| `cassandra-pattern-perception.md` | Thin-slicing, expert intuition, fast cognition, first impressions, code pattern recognition |
| `cassandra-cognitive-biases.md` | Kahneman System 1/2, WYSIATI, 60+ cognitive biases (memory, reasoning, social, decision, self-related), Bayesian reasoning, Signal Detection Theory |
| `cassandra-voice.txt` | Cassandra's voice and speech patterns reference |

---

## Infrastructure Reference

| File | Content |
|------|---------|
| `rag-and-memory.md` | How Layla's RAG pipeline works (BM25, cross-encoder, HyDE, parent-doc, FTS5) |
| `tools-reference.md` | All 29 tool descriptions with parameters and usage |
| `troubleshooting.md` | Common issues and fixes |
| `local-ai-models-guide.md` | GGUF models, quantization, GPU offloading, llama-cpp-python settings |
| `python-best-practices.md` | Additional Python best practices |

---

## Fetched Knowledge (runtime)

Stored in `knowledge/fetched/` — downloaded by `scripts/fetch_knowledge.py` or `agent/download_docs.py`.

These are NOT committed to git (gitignored) but are indexed locally when present:
- FastAPI docs
- SQLite documentation
- asyncio docs
- Python typing/pathlib/dataclasses references
- llama-cpp-python README

---

## Adding Your Own Knowledge

Drop any `.md`, `.txt`, or `.json` file into `knowledge/` and Layla will index it on next startup. Use YAML front matter to add context:

```yaml
---
priority: core    # core / high / medium / low
domain: my-domain
aspect: morrigan  # which aspect benefits most
---
```

Files in `knowledge/fetched/` are local only (gitignored). Files directly in `knowledge/` can be committed if added to `.gitignore` exceptions.

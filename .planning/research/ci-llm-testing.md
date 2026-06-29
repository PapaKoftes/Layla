# CI LLM Testing: How real local-LLM projects exercise inference without SIGILL / heavy builds

**Researched:** 2026-06-29
**Question:** How do real llama.cpp / llama-cpp-python / local-LLM projects test inference in CI without the SIGILL / heavy-build problem?
**Overall confidence:** HIGH on the mechanics (model, build flags, wheel index); MEDIUM on exact determinism guarantees (hardware-dependent — design around it, don't fight it).

---

## TL;DR for Layla

The current CI is correct to *block* the AVX-512 prebuilt wheel — but it blocks the **wrong layer**. Instead of `_block_llama_cpp_on_ci` (which makes `llama_cpp.Llama` raise and forces `collect_ignore` of the entire 4,119-line loop), do what llama.cpp itself does:

1. **Install a portable CPU wheel** built with `-DGGML_NATIVE=OFF` (no `-march=native`, no AVX-512 dispatch) — or pull abetlen's prebuilt CPU index.
2. **Ship a ~1 MB real GGUF** (`stories260K`, the exact model llama.cpp uses in its own CI) committed to the repo or downloaded once.
3. **Run the agent loop against it** with `seed` fixed + `top_k=1`, asserting on *structural* properties (stop honored, bounded token count, KV-cache multi-turn coherence), not exact strings.

This un-`collect_ignore`s `test_agent_loop.py` et al. safely, and gives the first real end-to-end inference coverage Layla has ever had in CI.

---

## 1. The actual root cause (Layla-specific)

From `agent/tests/conftest.py`:

- `_LLAMA_CPP_FILES` (10 files incl. `test_agent_loop.py`, `test_completion.py`, `test_engineering_pipeline.py`) are `collect_ignore`d when `CI` is set.
- `_block_llama_cpp_on_ci` replaces `llama_cpp.Llama.__init__` with a stub that raises `RuntimeError`.
- Rationale in-code: *"pre-compiled llama-cpp-python uses AVX-512/VNNI instructions unsupported by GitHub Actions VMs, causing a process-fatal SIGILL (exit 132)."*
- CI writes `runtime_config.json` with `model_filename: "ci-stub.gguf"`, `n_gpu_layers: 0`, `n_ctx: 2048`.

The seam everything routes through is `agent/services/llm_gateway.py::run_completion(prompt, max_tokens=256, temperature=0.2, stream=False, stop=None, ...)` → `services.inference_router.run_completion` → `llama_cpp` `create_completion`.

**The SIGILL is real**, not paranoia: GGML dispatches kernels by CPUID. A wheel compiled with `-march=native` on a Sapphire-Rapids builder bakes in AVX-512 paths; when CPUID *reports* AVX-512 but the hypervisor has it disabled (exactly the GitHub Actions / Google Cloud Run Sapphire-Rapids situation), the binary executes an illegal instruction and the OS kills the process — bypassing Python `try/except` entirely. ([Cloud Run SIGILL writeup](https://haitmg.pl/blog/cloud-run-sigill-avx512-llama-cpp/), [ggml #6723](https://github.com/ggml-org/llama.cpp/issues/6723))

So the fix is not "never run inference" — it's "run inference against a binary that doesn't dispatch instructions the runner can't execute."

---

## 2. Tiny real GGUF test models

| Model | Size | Repo / path | Notes | Confidence |
|-------|------|-------------|-------|------------|
| **stories260K** | **~1 MB** | `ggml-org/models` → `tinyllamas/stories260K.gguf` | **Used in llama.cpp's own CI.** Maintainer: *"stories260k is 1MB — you can hardly get smaller than that. We use it in the CI as well."* No Git-LFS needed. | HIGH |
| stories15M | ~58 MB (f32) / ~15 MB (q8) | `ggml-org/tiny-llamas`, also `klosax/tinyllamas-stories-gguf` | Karpathy's llama2.c stories models, converted to GGUF. Bigger but more "language-like" output. | HIGH |
| TinyLlama-1.1B Q2_K | ~482 MB | `TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF` | Smallest *chat-tuned* real model; produces coherent English, has a chat template. Too big to commit; download-on-demand only. | HIGH |
| TinyLlama-1.1B Q4_K_M | ~650 MB | same | Standard "small but real" choice for smoke tests where you need plausible chat output. | HIGH |

**Recommendation for Layla:** `stories260K` as the committed CI model (1 MB — fits in-repo or a cached download), with TinyLlama-1.1B-Q4 as an *optional* nightly job if you want output that looks like English (stories260K emits toy-story tokens, not chat).

Download (one-liner, cacheable in CI):

```bash
# 1 MB, no LFS
curl -L -o agent/tests/fixtures/stories260K.gguf \
  https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories260K.gguf
# or:
huggingface-cli download ggml-org/models tinyllamas/stories260K.gguf \
  --local-dir agent/tests/fixtures
```

Sources: [ggml-org/llama.cpp Discussion #6970 "Models for testing inference / sampling"](https://github.com/ggml-org/llama.cpp/discussions/6970), [ggml-org/models](https://huggingface.co/ggml-org/models), [klosax/tinyllamas-stories-gguf](https://huggingface.co/klosax/tinyllamas-stories-gguf), [TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF).

> Note: an 18-byte file is **not** a valid GGUF — it has no magic/header/tensors. `stories260K` is the smallest file that is a *real* model llama.cpp will actually load and generate from.

---

## 3. CPU-baseline llama-cpp-python build for CI (no AVX-512 SIGILL)

The whole problem is GGML's `-march=native` + runtime CPUID dispatch. Two ways to get a portable binary:

### Option A — Build from source with native dispatch OFF (most robust)

```bash
CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX512=OFF" \
  pip install --no-binary :all: llama-cpp-python
```

- `-DGGML_NATIVE=OFF` is the **key flag**: it disables `-march=native` and the auto-detect that bakes in whatever the *builder* CPU supports. Without it, none of the other flags reliably take effect (see [ggml #1583 "Cmake file always assumes AVX2"](https://github.com/ggml-org/llama.cpp/issues/1583) and [llama-cpp-python #284](https://github.com/abetlen/llama-cpp-python/issues/284) — `-DLLAMA_AVX2=OFF` alone was ignored when native was on).
- Add `-DGGML_AVX512=OFF` (and optionally `-DGGML_AVX2=OFF` for maximum portability — slower but guaranteed on any x86-64-v1 runner). With native off, GGML falls back to a conservative baseline.
- Cost: a from-source build is a few minutes; cache it (see CI plan).

> Modern GGML flag names use the `GGML_` prefix (`-DGGML_AVX2`, `-DGGML_AVX512`, `-DGGML_NATIVE`); the old `LLAMA_AVX*` names are deprecated aliases. Use `GGML_`.

### Option B — Prebuilt CPU wheel index (fastest, no compiler)

```bash
pip install llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

- Maintainer-published "basic CPU support" wheels. **Python 3.10 / 3.11 / 3.12** (matches Layla's 3.11+3.12 matrix; note 3.13/3.14 wheels are still a [tracked gap, issue #2136](https://github.com/abetlen/llama-cpp-python/issues/2136) — consistent with Layla's "3.12-only" reality).
- "basic CPU" here means a conservative baseline build — this is exactly what avoids the SIGILL. PyPI itself has **no** prebuilt wheels (a bare `pip install` builds an sdist from source).
- Risk: you don't control which ISA baseline the index wheel targets. If a future index wheel reintroduces AVX-512 dispatch, you're back to SIGILL. Option A is the deterministic choice; Option B is the convenient one. **Recommend A for the gating job, B acceptable for a non-gating smoke.**

Sources: [abetlen/llama-cpp-python README](https://github.com/abetlen/llama-cpp-python/blob/main/README.md?plain=1), [DeepWiki install guide](https://deepwiki.com/abetlen/llama-cpp-python/2-installation-and-setup), [Cloud Run SIGILL writeup](https://haitmg.pl/blog/cloud-run-sigill-avx512-llama-cpp/).

---

## 4. Mock the boundary vs run a real tiny model — pattern guidance

Both have a place; they answer different questions.

| Layer | What it proves | Cost | When |
|-------|----------------|------|------|
| **Mock `run_completion`** (Layla's existing `mock_llm` fixture, patches `services.llm_gateway.run_completion`) | Agent-loop *control flow*: tool dispatch, retry, JSON parsing, completion gate, KV/turn bookkeeping — given a *scripted* model reply. | ~ms | The bulk of loop tests. This is the right default and Layla already has it. |
| **Scripted-sequence mock** (a fake that returns a *list* of canned completions in order) | Multi-turn orchestration: "tool call → observe → final answer" without a real model. | ~ms | Engineering-pipeline / agent-loop tests that need >1 turn. Strongly recommended — most "loop" bugs are orchestration, not token generation. |
| **Real stories260K via `Llama`** | The *integration seam itself*: that `run_completion` correctly wires prompt→`create_completion`→parsed dict, stop sequences, `n_ctx`, KV cache reuse across turns actually function against a real binary. | ~100ms–1s/test | A small dedicated `inference_smoke` set. Catches exactly the class of bug that mocking *cannot*: a broken gateway/router wiring. |

**Key insight:** mocking `run_completion` will never catch a regression in `run_completion` or `inference_router` or the `llama_cpp` call shape — which is precisely the untested surface flagged in `TESTING.md`. You need *one* real-model job to cover that seam; everything else stays mocked for speed.

**How projects gate releases:** the common pattern (llama.cpp, llama-cpp-python, ollama) is a tiered gate — fast mocked/unit tests on every PR (blocking), a small real-tiny-model inference job on every PR (blocking, but bounded to seconds via stories260K + greedy + tiny `max_tokens`), and heavyweight real-model / GPU / quality-eval jobs nightly or on release tags (non-blocking for PRs). Layla already has the tiers (`slow`, `gpu_smoke`, etc.); it's just missing the small *blocking* real-inference rung.

---

## 5. Asserting on LLM output deterministically

**Hard truth (MEDIUM confidence, well-documented):** exact-string equality is fragile even at temp=0.

- Since [llama.cpp PR #9897 (Nov 2024)](https://github.com/ggml-org/llama.cpp/discussions/6970) `temperature=0` in the default sampler **no longer guarantees greedy** behavior (can cause repetition loops). For strict greedy, set **`top_k=1`** — don't rely on temp alone.
- Even with `seed` fixed + `top_k=1`, cross-machine determinism isn't guaranteed: parallel GGML kernels reorder float ops → tiny logit noise → occasional different argmax. ([llama.cpp #10197](https://github.com/ggml-org/llama.cpp/issues/10197), [llama-cpp-python #972](https://github.com/abetlen/llama-cpp-python/issues/972)). **On a single fixed CPU-only runner with the same binary this is far more stable**, but design assertions to tolerate it.

**Settings for maximum reproducibility** (use these in the inference smoke):

```python
from llama_cpp import Llama
llm = Llama(
    model_path="agent/tests/fixtures/stories260K.gguf",
    n_ctx=512, n_gpu_layers=0, seed=42, n_threads=1,  # n_threads=1 removes reduction-order nondeterminism
    verbose=False,
)
out = llm.create_completion(
    "Once upon a time",
    max_tokens=16, temperature=0.0, top_k=1, top_p=1.0, repeat_penalty=1.0,
    stop=["\n\n"], seed=42,
)
```

`n_threads=1` is the single most effective knob for reproducibility — it eliminates the parallel float-reduction reordering that defeats temp=0.

**What to assert (robust → strict):**

1. **Structural / contract** (always safe, the workhorse):
   - completion returns the expected dict shape (`out["choices"][0]["text"]` / `...["message"]["content"]`).
   - non-empty text; `len(tokens) <= max_tokens`.
   - **stop sequence honored**: output does not contain the stop string; finish_reason is `stop` when expected.
   - **multi-turn KV-cache correctness**: feed turn-1, then turn-2 reusing the cache; assert turn-2 starts coherently and that re-running turn-1 fresh vs cached yields the *same first token* (proves cache isn't corrupting state).
2. **Prefix stability** (medium strict): with `seed` + `top_k=1` + `n_threads=1`, assert the **first N tokens** are stable across runs (golden prefix), not the full string. First-token argmax is the most stable signal.
3. **Exact string** (only on a pinned single runner): acceptable for stories260K with the settings above if you accept it may need a re-baseline on toolchain bumps. Prefer #1/#2.

**For chat/agent-level assertions**, don't assert model wording at all — assert the **agent behavior**: "given a scripted model reply containing a `read_file` tool call, the loop dispatched `read_file`," "given a reply with a stop token the loop terminated," "max_tool_calls bounded the run." That's mock territory (§4) and is where Layla gets the most signal per millisecond.

Sources: [llama.cpp Discussion #6970](https://github.com/ggml-org/llama.cpp/discussions/6970), [llama.cpp #10197](https://github.com/ggml-org/llama.cpp/issues/10197), [llama-cpp-python #972](https://github.com/abetlen/llama-cpp-python/issues/972), [Vincent Schmalbach "Does Temperature 0 Guarantee Deterministic Output?"](https://www.vincentschmalbach.com/does-temperature-0-guarantee-deterministic-llm-outputs/).

---

## 6. Concrete CI plan for Layla

### New fixture: a real tiny model, gated and isolated

Add to `agent/tests/conftest.py`:

```python
import os, pytest
from pathlib import Path

_TINY_GGUF = Path(__file__).parent / "fixtures" / "stories260K.gguf"

@pytest.fixture(scope="session")
def tiny_llm():
    """Real 1MB GGUF for inference-seam smoke tests. Skips if model/binary absent."""
    if not _TINY_GGUF.exists():
        pytest.skip("stories260K.gguf not present (run scripts/fetch_ci_model.sh)")
    try:
        import llama_cpp
    except ImportError:
        pytest.skip("llama_cpp not installed")
    # IMPORTANT: do NOT let _block_llama_cpp_on_ci stub apply here.
    Llama = getattr(llama_cpp, "_RealLlama", llama_cpp.Llama)
    return Llama(model_path=str(_TINY_GGUF), n_ctx=512, n_gpu_layers=0,
                 seed=42, n_threads=1, verbose=False)
```

Mark these with a new `inference_smoke` marker so they're explicit and individually gateable.

### Un-ignoring the loop tests safely

The blunt `_block_llama_cpp_on_ci` + `collect_ignore` is the thing to retire. Migration path, lowest-risk first:

1. **Keep `collect_ignore` only for files that genuinely need it**, and shrink the list as you convert each file to use the `mock_llm` / scripted-sequence fixture. Most of `_LLAMA_CPP_FILES` reach `llama_cpp` *only because nothing mocked the gateway* — once they use `mock_llm`, they never touch native code and can leave `_LLAMA_CPP_FILES`. Audit each: does it test *orchestration* (→ mock, un-ignore) or *the inference seam* (→ tiny_llm smoke)?
2. **Replace the hard stub with a portable binary.** Once CI installs a `-DGGML_NATIVE=OFF` wheel (§3), `_block_llama_cpp_on_ci` is no longer protecting against anything — a real `Llama` load won't SIGILL. Reduce it to a no-op (or keep it only as a guard that *real* model loads are opt-in via the `tiny_llm` fixture, to keep the default suite fast).
3. **Add the inference-seam smoke** that loads stories260K and exercises `services.llm_gateway.run_completion` end-to-end (not the raw `Llama`), proving the gateway/router wiring.

### Suggested `ci.yml` jobs

```yaml
jobs:
  test:                 # existing — fast mocked suite, unchanged, blocking
    # ... fast subset, mock_llm everywhere, coverage floor (Linux)

  inference-smoke:      # NEW — blocking, ~1-2 min
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      # Portable CPU binary — the SIGILL fix
      - name: Install portable llama-cpp-python
        env:
          CMAKE_ARGS: "-DGGML_NATIVE=OFF -DGGML_AVX512=OFF"
        run: pip install --no-binary :all: llama-cpp-python
        # (fallback: pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu)
      - name: Cache / fetch tiny model
        run: |
          mkdir -p agent/tests/fixtures
          curl -L -o agent/tests/fixtures/stories260K.gguf \
            https://huggingface.co/ggml-org/models/resolve/main/tinyllamas/stories260K.gguf
      - name: Run inference-seam smoke
        working-directory: agent
        run: python -m pytest tests/ -m "inference_smoke" -v --timeout=120
        # CI=1 NOT set for this job (or _block_llama_cpp_on_ci made a no-op),
        # so the real Llama loads. Suite is tiny + portable → no SIGILL.

  test-windows:         # existing — unchanged
  e2e-ui:               # existing — unchanged
  lint:                 # existing — unchanged
```

Notes:
- **Cache the built wheel** (`actions/cache` on pip wheel dir, keyed by llama-cpp-python version + `CMAKE_ARGS`) so the from-source build runs once, not every push.
- **Cache the 1 MB model**, or just commit it — at 1 MB it's defensible in-repo (avoids HF rate limits / outages in CI). Committing is the more hermetic choice.
- Keep `inference-smoke` **separate** from the main `test` job so a model-download hiccup or a determinism flake never blocks the fast unit suite — but make it **required** for merge once stable, so the inference seam is genuinely gated.
- The existing `_block_llama_cpp_on_ci` + stub config stays valid for the *fast* `test` job (it should never load a real model); only the new `inference-smoke` job opts into real inference.

### What this buys Layla

- First-ever **real end-to-end inference coverage** in CI (the agent loop, gateway, and router seam against an actual GGUF).
- Most of the 10 `collect_ignore`d files become runnable once they mock the gateway — turning the 4,119-line loop from "never exercised in CI" into "orchestration fully exercised, inference-seam smoke-tested."
- No SIGILL risk, because the binary is built without the offending dispatch — the same fix llama.cpp itself ships.

---

## Sources

- [ggml-org/llama.cpp Discussion #6970 — Models for testing inference/sampling](https://github.com/ggml-org/llama.cpp/discussions/6970) (stories260K = CI model)
- [ggml-org/models on Hugging Face](https://huggingface.co/ggml-org/models) — `tinyllamas/stories260K.gguf`
- [klosax/tinyllamas-stories-gguf](https://huggingface.co/klosax/tinyllamas-stories-gguf)
- [TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF)
- [abetlen/llama-cpp-python README](https://github.com/abetlen/llama-cpp-python/blob/main/README.md?plain=1) — CMAKE_ARGS, CPU wheel index
- [abetlen/llama-cpp-python #284 — `-DLLAMA_AVX2=OFF` ignored without GGML_NATIVE=OFF](https://github.com/abetlen/llama-cpp-python/issues/284)
- [abetlen/llama-cpp-python #2136 — prebuilt wheel py-version coverage (3.13/3.14 gap)](https://github.com/abetlen/llama-cpp-python/issues/2136)
- [ggml-org/llama.cpp #1583 — cmake always assumes AVX2](https://github.com/ggml-org/llama.cpp/issues/1583)
- [ggml-org/llama.cpp #6723 — AVX generated despite host without AVX](https://github.com/ggml-org/llama.cpp/issues/6723)
- [Cloud Run SIGILL: Sapphire Rapids broke llama.cpp AVX-512](https://haitmg.pl/blog/cloud-run-sigill-avx512-llama-cpp/) (the exact CPUID-vs-hypervisor mechanism behind Layla's exit 132)
- [ggml-org/llama.cpp #10197 — nondeterminism despite seed+temp0](https://github.com/ggml-org/llama.cpp/issues/10197)
- [abetlen/llama-cpp-python #972 — most deterministic output settings](https://github.com/abetlen/llama-cpp-python/issues/972)
- [Vincent Schmalbach — Does Temperature 0 Guarantee Deterministic Output?](https://www.vincentschmalbach.com/does-temperature-0-guarantee-deterministic-llm-outputs/)

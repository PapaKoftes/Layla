# Fine-tuning Layla (same model, RAG + data export)

You’re not changing the **model** (Jinx 20B GGUF); you’re making the most of it with RAG and optional fine-tuning on her identity and data.

## 1. RAG (already in place)

- **Chroma + FAISS** are both used: learnings are written to both; retrieval merges and dedupes results so you get the best of both.
- **Knowledge** is indexed in Chroma at startup; relevant chunks are pulled per turn.
- **System prompt** starts with a fixed “core instructions” block so identity isn’t pushed out by long context.

No extra steps; this is how the agent runs now.

## 2. Export fine-tune data

From the **repo root**:

```bash
python agent/export_finetune_data.py
```

This writes **`agent/finetune_data.jsonl`** with chat-format records built from:

- `agent/system_identity.txt`
- `personality.json` and `personalities/*.json` (each aspect’s voice + a trigger → reply)
- Recent **learnings** (as “Remember: …” / “I’ll remember: …”)
- A sample of **aspect_memories** (in-character observations)

Each line is one conversation: `{"messages": [{"role": "system"|"user"|"assistant", "content": "..."}, ...]}`.

## 3. Using the exported data to fine-tune

You keep the **same base model** (e.g. Jinx 20B); fine-tuning adapts it to Layla’s identity and style.

- **llama.cpp**  
  Convert your JSONL to the format expected by [llama.cpp’s finetuning](https://github.com/ggerganov/llama.cpp#fine-tuning) (e.g. one tokenized example per line or their recommended format). Then run their fine-tune script and re-export to GGUF so you can drop the new file into `models/` and point `model_filename` at it.

- **Unsloth / Hugging Face**  
  Use `finetune_data.jsonl` with a trainer that accepts chat-style JSONL (e.g. Unsloth, LLaMA-Factory). Load the **base** model that corresponds to your current GGUF (same architecture/family), fine-tune on the exported data, then export to GGUF and replace (or add) the model in `models/`.

- **Other pipelines**  
  Any tool that accepts chat `messages` (system/user/assistant) can consume this file; you may need a small script to map fields to their expected names.

After fine-tuning, put the new GGUF in `models/`, set `model_filename` in `runtime_config.json`, and run as usual. RAG and the rest of the stack stay the same; the model just behaves more like Layla out of the box.

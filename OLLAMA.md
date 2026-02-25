# Using Ollama with Layla

Ollama runs open models locally with an OpenAI-compatible API. One config change and Layla uses a much stronger brain.

## 1. Install Ollama

- **Windows:** [ollama.com](https://ollama.com) → download and install.
- Then in a terminal: `ollama pull llama3.1` (or `mistral`, `qwen2.5-coder`, `deepseek-r1`, etc.).

## 2. Point Layla at Ollama

In `agent/runtime_config.json` set:

```json
"llama_server_url": "http://localhost:11434",
"remote_model_name": "llama3.1"
```

Use the same model name you pulled (e.g. `mistral`, `llama3.1:8b`, `qwen2.5-coder:7b`).

## 3. Restart the agent

```bash
cd agent
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

She will now call Ollama for completions instead of loading a GGUF. No code changes needed.

## Suggested models

| Model | Command | Best for |
|-------|---------|----------|
| Llama 3.1 8B | `ollama pull llama3.1` | General chat + code |
| Mistral 7B | `ollama pull mistral` | Fast, sharp |
| Qwen2.5 Coder | `ollama pull qwen2.5-coder` | Morrigan (coding) |
| DeepSeek R1 | `ollama pull deepseek-r1` | Deliberation / reasoning |

Increase `n_ctx` (e.g. 8192) and `completion_max_tokens` (e.g. 512) in config for longer context and replies.

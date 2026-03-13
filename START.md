# Start Layla

One command to run the chat server so you can talk to her in the browser.

## 1. From repo root

```bash
cd agent
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 2. Open the UI

In your browser: **http://127.0.0.1:8000**

You’ll see the greeting from Echo, the chat area, and the **Voices** sidebar (Morrigan, Nyx, Echo, Eris, Lilith). Type in the box and hit **Send**, or turn on **Stream** to see her reply as it types, and **Her thoughts** to have her deliberate with her inner voices before answering. Lilith's NSFW register is toggled by including a keyword (e.g. intimate, nsfw) in your message.

## 3. (Optional) Cursor MCP

To use Layla from Cursor, start the MCP server from the project root, then **use the MCP tools** (e.g. “Chat with Layla (Jinx)” / `chat_with_layla`) with your message in the tool’s `message` argument. Do not type plain chat into a stream that sends raw text to MCP — that causes “Invalid JSON” errors because MCP expects JSON-RPC.

```bash
cd cursor-layla-mcp
python server.py
```

(Ensure the web server above is already running on port 8000.) For free-form chat, use the browser UI at http://127.0.0.1:8000.

---

**First time?** Put your GGUF model in `models/` and set `model_filename` in `agent/runtime_config.json` if needed. She remembers and grows across sessions (learnings, study plans, aspect memories) in `layla.db`.

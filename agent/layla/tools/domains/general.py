"""General context, goals, utilities, and meta tools."""

TOOLS = {
    "get_project_context": {
        "fn_key": "get_project_context_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Retrieve the current project context: goals, progress, workspace summary, and open issues.",
    },
    "update_project_context": {
        "fn_key": "update_project_context_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Update the project context with new observations, goals, or status changes.",
    },
    "get_user_identity": {
        "fn_key": "get_user_identity_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "memory",
        "description": "Retrieve the stored user identity profile: name, preferences, and technical domains.",
    },
    "update_user_identity": {
        "fn_key": "update_user_identity_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "memory",
        "description": "Update the user identity profile with new information or preferences.",
    },
    "add_goal": {
        "fn_key": "add_goal_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Create a new tracked goal with a description and optional deadline.",
    },
    "add_goal_progress": {
        "fn_key": "add_goal_progress_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Record progress against an existing goal. Logs what was accomplished.",
    },
    "get_active_goals": {
        "fn_key": "get_active_goals_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "List all active goals with their progress, status, and recent updates.",
    },
    "list_tools": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "List all available tools with their categories, risk levels, and descriptions.",
    },
    "tool_recommend": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Suggest the best tools for a given task based on past success patterns.",
    },
    "image_resize": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Resize an image to specified dimensions or scale factor.",
    },
    "extract_frames": {
        "dangerous": False, "require_approval": False, "risk_level": "medium",
        "category": "filesystem",
        "description": "Extract individual frames from a video file at specified intervals.",
    },
    "detect_scenes": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Detect scene changes in a video and return timestamps of transitions.",
    },
    "detect_objects": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Detect objects in an image using a pre-trained model and return bounding boxes.",
    },
    "geo_query": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "search",
        "description": "Look up geographic coordinates, addresses, or place names.",
    },
    "map_url": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "search",
        "description": "Generate a map URL for given coordinates or address for viewing.",
    },
    "uuid_generate": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Generate a new UUID (v4) for use as a unique identifier.",
    },
    "random_string": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Generate a random string of specified length and character set.",
    },
    "password_generate": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Generate a secure random password with configurable length and complexity.",
    },
    "string_transform": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Transform text: case conversion, slug, camel/snake case, URL encode/decode.",
    },
    "timestamp_convert": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Convert between timestamp formats: Unix epoch, ISO 8601, human-readable.",
    },
    "generate_qr": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Generate a QR code image from text or a URL.",
    },
    "json_schema": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Generate a JSON Schema from sample data or validate data against a schema.",
    },
    "jwt_decode": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Decode a JWT token and display its header, payload, and expiration status.",
    },
    "create_svg": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Create an SVG image from a description or structured drawing commands.",
    },
    "create_mermaid": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Generate a Mermaid diagram (flowchart, sequence, class, etc.) from a description.",
    },
    "log_event": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Log a structured event to the audit trail for debugging and traceability.",
    },
    "trace_last_run": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Show a trace of the last agent run: steps taken, tools called, and decisions made.",
    },
    "tool_metrics": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Show tool usage statistics: call counts, success rates, and average latency.",
    },
    "stt_file": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "voice",
        "description": "Transcribe an audio file to text using speech-to-text (Whisper or system STT).",
    },
    "tts_speak": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "voice",
        "description": "Convert text to speech audio using the configured TTS engine.",
    },
    "crypto_prices": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "search",
        "description": "Fetch current cryptocurrency prices and 24h change for given symbols.",
    },
    "economic_indicators": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "search",
        "description": "Fetch key economic indicators: GDP, inflation, unemployment, interest rates.",
    },
    "structured_llm_task": {
        "fn_key": "structured_llm_task",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Run a structured LLM task with a JSON schema for the output format.",
    },
    "mcp_tools_call": {
        "fn_key": "mcp_tools_call",
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "system",
        "description": "Call a tool on a connected MCP server by name with the given arguments.",
    },
    "mcp_list_mcp_tools": {
        "fn_key": "mcp_list_mcp_tools",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "List all tools available on connected MCP servers.",
    },
    "mcp_list_mcp_resources": {
        "fn_key": "mcp_list_mcp_resources",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "List all resources exposed by connected MCP servers.",
    },
    "mcp_read_mcp_resource": {
        "fn_key": "mcp_read_mcp_resource",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Read a specific resource from a connected MCP server by URI.",
    },
    "mcp_operator_auth_hint": {
        "fn_key": "mcp_operator_auth_hint",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Get authentication hints for an MCP server that requires operator authorization.",
    },
    "notebook_read_cells": {
        "fn_key": "notebook_read_cells",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Read all cells from a Jupyter notebook with their types, sources, and outputs.",
    },
    "notebook_edit_cell": {
        "fn_key": "notebook_edit_cell",
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Edit a specific cell in a Jupyter notebook by index, replacing its source code.",
    },
}

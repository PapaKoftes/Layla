"""File system and document tools."""

TOOLS = {
    "write_file": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "filesystem",
        "description": "Create or overwrite a file with the given content. Returns the path written.",
    },
    "write_files_batch": {
        "dangerous": True, "require_approval": True, "risk_level": "high",
        "category": "filesystem",
        "description": "Write multiple files in a single atomic operation. Each entry specifies a path and content.",
    },
    "read_file": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "Read the contents of a file. Returns text with line numbers for easy reference.",
    },
    "list_dir": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "List files and subdirectories in a directory. Returns names, sizes, and modification times.",
    },
    "tail_file": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "Read the last N lines of a file. Useful for logs and growing output files.",
    },
    "file_info": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "Get metadata about a file: size, modification time, permissions, and type.",
    },
    "glob_files": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "Find files matching a glob pattern (e.g. **/*.py). Returns matching paths sorted by modification time.",
    },
    "diff_files": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "Compute a unified diff between two files. Shows added, removed, and changed lines.",
    },
    "parse_gcode": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Parse a G-code file and extract move commands, tool changes, and estimated machining time.",
    },
    "stl_mesh_info": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "fabrication",
        "description": "Read an STL mesh file and report vertex count, face count, bounding box, and volume estimate.",
    },
    "clipboard_read": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Read the current contents of the system clipboard.",
    },
    "clipboard_write": {
        "dangerous": False, "require_approval": True, "risk_level": "medium",
        "category": "system",
        "description": "Write text to the system clipboard, replacing its current contents.",
    },
    "search_replace": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "filesystem",
        "description": "Find and replace text in a file. Supports exact string and regex patterns.",
    },
    "replace_in_file": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "filesystem",
        "description": "Replace all occurrences of a string in a file. Returns count of replacements made.",
    },
    "apply_patch": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "filesystem",
        "description": "Apply a unified diff patch to one or more files. Validates the patch before applying.",
    },
    "json_query": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "Query a JSON file using JMESPath expressions. Returns matching values.",
    },
    "understand_file": {
        "fn_key": "understand_file_tool",
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Analyze a source file and return a structured summary: imports, classes, functions, and key logic.",
    },
    "workspace_map": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "code",
        "description": "Generate a tree map of the workspace showing directory structure and file types.",
    },
    "sync_repo_cognition": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "code",
        "description": "Refresh the semantic index of the current repository for faster code search.",
    },
    "scan_repo": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "code",
        "description": "Deep scan a repository: index all files, extract symbols, build dependency graph.",
    },
    "update_project_memory": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "memory",
        "description": "Update the persistent project memory with new observations about the workspace.",
    },
    "read_pdf": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Extract text content from a PDF file. Supports multi-page documents.",
    },
    "read_docx": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Extract text and basic formatting from a Word (.docx) document.",
    },
    "read_excel": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Read an Excel spreadsheet and return cell data as structured rows and columns.",
    },
    "hash_file": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Compute the SHA-256 hash of a file for integrity verification.",
    },
    "yaml_read": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Parse a YAML file and return its contents as structured data.",
    },
    "xml_parse": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Parse an XML file and return elements as structured data. Supports XPath queries.",
    },
    "read_toml": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Parse a TOML configuration file and return its contents as structured data.",
    },
    "merge_pdf": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Merge multiple PDF files into a single document.",
    },
    "write_csv": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "filesystem",
        "description": "Write structured data to a CSV file with configurable delimiter and headers.",
    },
    "extract_archive": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Extract a compressed archive (.zip, .tar.gz, .7z) to a target directory.",
    },
    "create_archive": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Create a compressed archive from files or directories.",
    },
    "base64_tool": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "filesystem",
        "description": "Encode or decode data using Base64. Useful for binary-to-text conversions.",
    },
    "list_file_checkpoints": {
        "dangerous": False, "require_approval": False, "risk_level": "low", "concurrency_safe": True,
        "category": "filesystem",
        "description": "List saved checkpoints (backup snapshots) for a file, with timestamps.",
    },
    "restore_file_checkpoint": {
        "dangerous": True, "require_approval": True, "risk_level": "medium",
        "category": "filesystem",
        "description": "Restore a file to a previously saved checkpoint, reverting recent changes.",
    },
}

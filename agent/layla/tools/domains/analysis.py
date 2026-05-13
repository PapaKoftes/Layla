"""Math, NLP, visualization, and analysis tools."""

TOOLS = {
    "math_eval": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Evaluate a mathematical expression and return the result. Supports basic and scientific math.",
    },
    "sympy_solve": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Solve algebraic equations, simplify expressions, or compute derivatives/integrals using SymPy.",
    },
    "nlp_analyze": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Analyze text: sentiment, named entities, key phrases, readability, and language detection.",
    },
    "ocr_image": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Extract text from an image using optical character recognition (Tesseract OCR).",
    },
    "plot_chart": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Generate a chart (line, bar, pie, area) from data and save it as an image.",
    },
    "describe_image": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Generate a text description of an image using a vision model.",
    },
    "summarize_text": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Summarize long text into a concise version, preserving key points.",
    },
    "classify_text": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Classify text into categories using a zero-shot or trained classifier.",
    },
    "translate_text": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Translate text between languages. Auto-detects source language.",
    },
    "text_stats": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Compute text statistics: word count, sentence count, reading level, and vocabulary richness.",
    },
    "embedding_generate": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Generate a vector embedding for text using the configured embedding model.",
    },
    "extract_entities": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Extract named entities (people, places, organizations, dates) from text.",
    },
    "sentiment_timeline": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Track sentiment changes over a series of text entries and plot a timeline.",
    },
    "plot_scatter": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Generate a scatter plot from x/y data points and save it as an image.",
    },
    "plot_histogram": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Generate a histogram from numeric data with configurable bins.",
    },
    "tool_chain_plan": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "planning",
        "description": "Plan a chain of tool calls to accomplish a complex task. Returns ordered steps with dependencies.",
    },
    "count_tokens": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Count the number of tokens in a text string for a given model's tokenizer.",
    },
    "regex_test": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "code",
        "description": "Test a regular expression against input text and return all matches with groups.",
    },
    "context_compress": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "system",
        "description": "Compress context text using LLMLingua or heuristic pruning to reduce token count.",
    },
}

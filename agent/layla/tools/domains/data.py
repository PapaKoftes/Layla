"""Data, database, and analytics tools."""

TOOLS = {
    "read_csv": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Read a CSV file and return its contents as structured rows with headers.",
    },
    "sql_query": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Execute a read-only SQL query against a SQLite or PostgreSQL database.",
    },
    "schema_introspect": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Inspect a database schema: list tables, columns, types, indexes, and foreign keys.",
    },
    "stock_data": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "search",
        "description": "Fetch historical or real-time stock price data for a given ticker symbol.",
    },
    "generate_sql": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Generate a SQL query from a natural language description of the desired result.",
    },
    "dataset_summary": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Compute summary statistics for a dataset: row count, column types, missing values, distributions.",
    },
    "cluster_data": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Cluster data points using k-means or DBSCAN and return cluster assignments.",
    },
    "scipy_compute": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Run a SciPy computation: optimization, interpolation, statistics, or signal processing.",
    },
    "db_backup": {
        "dangerous": False, "require_approval": False, "risk_level": "low",
        "category": "data",
        "description": "Create a backup copy of a SQLite database file with a timestamped filename.",
    },
}

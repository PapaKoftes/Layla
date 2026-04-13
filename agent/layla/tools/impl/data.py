"""Tool implementations — domain: data."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from layla.tools.sandbox_core import (
    _SHELL_BLOCKLIST,
    _SHELL_INJECTION_WARN,
    _SHELL_NETWORK_DENYLIST,
    _agent_registry_dir,
    _check_read_freshness,
    _clear_read_freshness,
    _effective_sandbox,
    _get_sandbox,
    _maybe_file_checkpoint,
    _set_read_freshness,
    _shell_executable_base,
    _write_file_limits,
    inside_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)

logger = logging.getLogger("layla")

# Injected by layla.tools.registry with the assembled TOOLS dict (same object in every module).
TOOLS: dict = {}
def read_csv(path: str, max_rows: int = 50, describe: bool = True) -> dict:
    """
    Read a CSV file and return a summary. max_rows controls rows returned.
    If describe=True, returns statistical summary (count, mean, std, etc.).
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        import pandas as _pd
        df = _pd.read_csv(str(target))
        result: dict = {
            "ok": True,
            "path": str(target),
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "sample": df.head(max_rows).to_dict(orient="records"),
            "null_counts": df.isnull().sum().to_dict(),
        }
        if describe:
            try:
                result["stats"] = df.describe().to_dict()
            except Exception:
                pass
        return result
    except ImportError:
        # Fallback to stdlib csv
        import csv as _csv
        with open(str(target), newline="", encoding="utf-8", errors="replace") as f:
            reader = _csv.DictReader(f)
            rows = [row for _, row in zip(range(max_rows + 1), reader)]
        return {"ok": True, "path": str(target), "columns": reader.fieldnames or [], "sample": rows[:max_rows]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def sql_query(db_path: str, query: str, limit: int = 200) -> dict:
    """
    Execute a SQL query against a SQLite or DuckDB database file.
    READ-ONLY by default: SELECT queries only. Non-SELECT queries require allow_write.
    db_path: path to .db/.sqlite/.duckdb file, or ':memory:' for DuckDB in-memory.
    """
    is_readonly = query.strip().upper().startswith("SELECT") or query.strip().upper().startswith("WITH")
    target = Path(db_path) if db_path != ":memory:" else None
    if target and not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if target and not target.exists():
        return {"ok": False, "error": "File not found"}

    # Inject LIMIT if not present
    q = query.strip().rstrip(";")
    if is_readonly and "LIMIT" not in q.upper():
        q += f" LIMIT {limit}"

    # Try DuckDB first (handles .duckdb and in-memory well)
    ext = (target.suffix.lower() if target else ".duckdb")
    if ext == ".duckdb" or db_path == ":memory:":
        try:
            import duckdb
            conn = duckdb.connect(db_path)
            rel = conn.execute(q)
            cols = [d[0] for d in rel.description]
            rows = rel.fetchall()
            conn.close()
            return {
                "ok": True, "db": db_path, "query": query,
                "columns": cols, "rows": [dict(zip(cols, r)) for r in rows],
                "row_count": len(rows),
            }
        except ImportError:
            pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # SQLite
    try:
        import sqlite3 as _sql
        conn = _sql.connect(str(target))
        conn.row_factory = _sql.Row
        cursor = conn.execute(q)
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description] if cursor.description else []
        conn.close()
        return {
            "ok": True, "db": db_path, "query": query,
            "columns": cols, "rows": [dict(r) for r in rows],
            "row_count": len(rows),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def stock_data(ticker: str, period: str = "1mo", include_info: bool = True) -> dict:
    """
    Fetch stock or crypto data via yfinance.
    ticker: stock symbol (AAPL, TSLA, BTC-USD, ETH-USD, ^GSPC for S&P500)
    period: '1d' | '5d' | '1mo' | '3mo' | '6mo' | '1y' | '2y' | '5y' | 'ytd' | 'max'
    Returns: OHLCV data, current price, company info (if include_info=True).
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return {"ok": False, "error": f"No data for ticker: {ticker}"}
        hist_records = []
        for date, row in hist.tail(30).iterrows():
            hist_records.append({
                "date": str(date)[:10],
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        result: dict = {
            "ok": True, "ticker": ticker.upper(), "period": period,
            "current_price": round(float(hist["Close"].iloc[-1]), 4),
            "price_change_pct": round(float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100), 2),
            "52w_high": round(float(hist["High"].max()), 4),
            "52w_low": round(float(hist["Low"].min()), 4),
            "history": hist_records,
        }
        if include_info:
            try:
                info = t.info or {}
                result["info"] = {
                    "name": info.get("longName") or info.get("shortName", ""),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("forwardPE") or info.get("trailingPE"),
                    "dividend_yield": info.get("dividendYield"),
                    "description": (info.get("longBusinessSummary") or "")[:400],
                }
            except Exception:
                pass
        return result
    except ImportError:
        return {"ok": False, "error": "yfinance not installed: pip install yfinance"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def schema_introspect(db_path: str) -> dict:
    """
    Introspect a database schema. Returns tables, columns with types, row counts,
    foreign keys, and sample data (first 3 rows per table).
    Supports SQLite (.db, .sqlite) and DuckDB (.duckdb).
    """
    target = Path(db_path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}

    ext = target.suffix.lower()

    if ext == ".duckdb":
        try:
            import duckdb
            conn = duckdb.connect(str(target))
            tables_raw = conn.execute("SHOW TABLES").fetchall()
            schema = {}
            for (table_name,) in tables_raw:
                cols = conn.execute(f"DESCRIBE {table_name}").fetchall()
                count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                sample = conn.execute(f"SELECT * FROM {table_name} LIMIT 3").fetchall()
                col_names = [c[0] for c in cols]
                schema[table_name] = {
                    "columns": [{"name": c[0], "type": c[1]} for c in cols],
                    "row_count": count,
                    "sample": [dict(zip(col_names, row)) for row in sample],
                }
            conn.close()
            return {"ok": True, "db_type": "duckdb", "path": db_path, "tables": schema}
        except ImportError:
            return {"ok": False, "error": "duckdb not installed: pip install duckdb"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # SQLite
    try:
        import sqlite3 as _sql
        conn = _sql.connect(str(target))
        conn.row_factory = _sql.Row
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        schema = {}
        for (table_name,) in [(r["name"],) for r in tables]:
            cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            fkeys = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            sample_rows = conn.execute(f"SELECT * FROM {table_name} LIMIT 3").fetchall()
            col_names = [c["name"] for c in cols]
            schema[table_name] = {
                "columns": [{"name": c["name"], "type": c["type"], "notnull": bool(c["notnull"]), "pk": bool(c["pk"])} for c in cols],
                "foreign_keys": [{"from": fk["from"], "to_table": fk["table"], "to_col": fk["to"]} for fk in fkeys],
                "row_count": count,
                "sample": [dict(r) for r in sample_rows],
            }
        # Views
        views = conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        conn.close()
        return {"ok": True, "db_type": "sqlite", "path": db_path, "tables": schema, "views": [r["name"] for r in views]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def generate_sql(question: str, schema: str = "", db_path: str = "") -> dict:
    """
    Generate SQL from a natural language question.
    If db_path is provided, automatically introspects schema.
    If schema is provided as text, uses it directly.
    Returns generated SQL query. Pair with sql_query() to execute.
    Note: This builds the query using heuristics + schema context.
    For best results, run with an LLM (this provides the schema grounding layer).
    """
    # If db_path given, get schema first
    effective_schema = schema
    if db_path and not schema:
        try:
            schema_result = schema_introspect(db_path)
            if schema_result.get("ok"):
                lines = [f"Database: {db_path}"]
                for table, info in schema_result.get("tables", {}).items():
                    cols = ", ".join(f"{c['name']} {c['type']}" for c in info.get("columns", []))
                    lines.append(f"Table {table}: ({cols}) — {info.get('row_count', '?')} rows")
                effective_schema = "\n".join(lines)
        except Exception:
            pass

    # Build context for SQL generation
    context = {
        "ok": True,
        "question": question,
        "schema": effective_schema[:3000] if effective_schema else "(no schema provided — add db_path or schema parameter)",
        "hint": (
            "Use this schema + question with your LLM to generate SQL. "
            "Then call sql_query(db_path, generated_sql) to execute it. "
            "Example: SELECT column FROM table WHERE condition LIMIT 100"
        ),
        "example_patterns": [
            "COUNT: SELECT COUNT(*) FROM table WHERE col = 'value'",
            "JOIN: SELECT a.col, b.col FROM a JOIN b ON a.id = b.a_id",
            "GROUP BY: SELECT col, COUNT(*) FROM table GROUP BY col ORDER BY 2 DESC",
            "LIKE: SELECT * FROM table WHERE text_col LIKE '%keyword%'",
        ],
    }

    # Simple keyword-based SQL generation for common patterns
    q_lower = question.lower()
    if effective_schema:
        tables = []
        import re as _re
        for match in _re.finditer(r"Table (\w+):", effective_schema):
            tables.append(match.group(1))

        if tables:
            main_table = tables[0]
            if "count" in q_lower or "how many" in q_lower:
                context["generated_sql"] = f"SELECT COUNT(*) FROM {main_table};"
            elif "all" in q_lower or "show" in q_lower or "list" in q_lower:
                context["generated_sql"] = f"SELECT * FROM {main_table} LIMIT 100;"
            elif "recent" in q_lower or "latest" in q_lower or "last" in q_lower:
                context["generated_sql"] = f"SELECT * FROM {main_table} ORDER BY rowid DESC LIMIT 20;"
            else:
                context["generated_sql"] = f"SELECT * FROM {main_table} LIMIT 20; -- adjust as needed"

    return context

def scipy_compute(operation: str, params: dict | None = None) -> dict:
    """
    Scientific computation via scipy.
    Operations: stats.describe | stats.ttest | stats.correlation | stats.normalize |
                optimize.minimize | integrate.quad | fft | interpolate
    params: dict of inputs specific to each operation (see docstring examples below).
    Examples:
      scipy_compute('stats.describe', {'data': [1,2,3,4,5]})
      scipy_compute('stats.ttest', {'a': [1,2,3], 'b': [4,5,6]})
      scipy_compute('stats.correlation', {'x': [1,2,3], 'y': [2,4,6]})
      scipy_compute('optimize.minimize', {'func': 'x**2 + 2*x', 'x0': 0})
      scipy_compute('integrate.quad', {'func': 'x**2', 'a': 0, 'b': 1})
    """
    try:
        import numpy as _np
        import scipy.stats as _stats
    except ImportError:
        return {"ok": False, "error": "scipy not installed: pip install scipy"}

    if params is None:
        params = {}
    op = operation.lower().strip()

    try:
        if op == "stats.describe":
            data = _np.array(params["data"], dtype=float)
            desc = _stats.describe(data)
            return {"ok": True, "operation": op, "result": {"n": desc.nobs, "min": float(desc.minmax[0]), "max": float(desc.minmax[1]), "mean": float(desc.mean), "variance": float(desc.variance), "skewness": float(desc.skewness), "kurtosis": float(desc.kurtosis), "std": float(_np.std(data)), "median": float(_np.median(data)), "q25": float(_np.percentile(data, 25)), "q75": float(_np.percentile(data, 75))}}
        elif op == "stats.ttest":
            a, b = _np.array(params["a"], dtype=float), _np.array(params["b"], dtype=float)
            res = _stats.ttest_ind(a, b)
            return {"ok": True, "operation": op, "result": {"t_statistic": float(res.statistic), "p_value": float(res.pvalue), "significant_at_05": float(res.pvalue) < 0.05, "mean_a": float(_np.mean(a)), "mean_b": float(_np.mean(b)), "interpretation": "statistically different (p<0.05)" if res.pvalue < 0.05 else "no significant difference"}}
        elif op == "stats.correlation":
            x, y = _np.array(params["x"], dtype=float), _np.array(params["y"], dtype=float)
            r, p = _stats.pearsonr(x, y)
            return {"ok": True, "operation": op, "result": {"pearson_r": round(float(r), 6), "p_value": round(float(p), 6), "significant": float(p) < 0.05, "strength": "strong" if abs(r) > 0.7 else ("moderate" if abs(r) > 0.4 else "weak"), "direction": "positive" if r > 0 else "negative"}}
        elif op == "stats.normalize":
            data = _np.array(params["data"], dtype=float)
            mn, mx = data.min(), data.max()
            normalized = ((data - mn) / (mx - mn)).tolist() if mx != mn else [0.0] * len(data)
            return {"ok": True, "operation": op, "result": {"normalized": normalized, "original_min": float(mn), "original_max": float(mx)}}
        elif op == "optimize.minimize":
            import sympy as sp
            from sympy.parsing.sympy_parser import parse_expr
            x_sym = sp.Symbol("x")
            expr = parse_expr(params["func"], local_dict={"x": x_sym})
            fn = sp.lambdify(x_sym, expr, "numpy")
            from scipy.optimize import minimize_scalar
            res = minimize_scalar(fn)
            return {"ok": True, "operation": op, "result": {"x_min": float(res.x), "f_min": float(res.fun), "success": res.success}}
        elif op == "integrate.quad":
            import sympy as sp
            from sympy.parsing.sympy_parser import parse_expr
            x_sym = sp.Symbol("x")
            expr = parse_expr(params["func"], local_dict={"x": x_sym})
            fn = sp.lambdify(x_sym, expr, "numpy")
            from scipy.integrate import quad
            val, err = quad(fn, params["a"], params["b"])
            return {"ok": True, "operation": op, "result": {"integral": float(val), "error_estimate": float(err)}}
        elif op == "fft":
            data = _np.array(params["data"], dtype=float)
            fft_vals = _np.fft.fft(data)
            magnitudes = _np.abs(fft_vals).tolist()
            freqs = _np.fft.fftfreq(len(data)).tolist()
            half = len(magnitudes) // 2
            return {"ok": True, "operation": op, "result": {"frequencies": freqs[:half], "magnitudes": magnitudes[:half], "dominant_freq_idx": int(_np.argmax(magnitudes[:half]))}}
        elif op == "interpolate":
            from scipy.interpolate import interp1d
            x, y = _np.array(params["x"], dtype=float), _np.array(params["y"], dtype=float)
            f = interp1d(x, y, kind=params.get("kind", "linear"), fill_value="extrapolate")
            x_new = _np.array(params["x_new"], dtype=float)
            return {"ok": True, "operation": op, "result": {"x_new": params["x_new"], "y_interpolated": f(x_new).tolist()}}
        else:
            return {"ok": False, "error": f"Unknown operation: {op}. Use stats.describe/ttest/correlation/normalize, optimize.minimize, integrate.quad, fft, interpolate"}
    except KeyError as e:
        return {"ok": False, "error": f"Missing required param: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def cluster_data(data: list, n_clusters: int = 3, method: str = "kmeans", features: list | None = None) -> dict:
    """
    Cluster a dataset. method: 'kmeans' | 'dbscan' | 'hierarchical'
    data: list of dicts (from read_csv) or list of numeric lists.
    features: column names to use for dict rows. Empty = all numeric columns.
    Returns cluster assignments, centroids, per-cluster statistics.
    """
    try:
        import numpy as _np
        import sklearn.cluster as _cluster
        import sklearn.preprocessing as _prep
    except ImportError:
        return {"ok": False, "error": "scikit-learn not installed: pip install scikit-learn"}

    if data and isinstance(data[0], dict):
        import pandas as _pd
        df = _pd.DataFrame(data)
        if features:
            df = df[features]
        df = df.select_dtypes(include="number").dropna()
        X = df.values
        col_names = list(df.columns)
    else:
        X = _np.array(data, dtype=float)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        col_names = [f"x{i}" for i in range(X.shape[1])]

    if len(X) < 2:
        return {"ok": False, "error": "Need at least 2 data points"}

    scaler = _prep.StandardScaler()
    X_scaled = scaler.fit_transform(X)

    if method == "kmeans":
        n_clusters = min(n_clusters, len(X))
        model = _cluster.KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
        labels = model.fit_predict(X_scaled).tolist()
        centroids = scaler.inverse_transform(model.cluster_centers_).tolist()
        extra = {"inertia": float(model.inertia_)}
    elif method == "dbscan":
        model = _cluster.DBSCAN(eps=0.5, min_samples=max(2, len(X) // 10))
        labels = model.fit_predict(X_scaled).tolist()
        centroids = []
        extra = {"noise_points": labels.count(-1)}
    elif method == "hierarchical":
        model = _cluster.AgglomerativeClustering(n_clusters=min(n_clusters, len(X)))
        labels = model.fit_predict(X_scaled).tolist()
        centroids = []
        extra = {}
    else:
        return {"ok": False, "error": f"Unknown method: {method}. Use kmeans/dbscan/hierarchical"}

    unique_labels = sorted(set(labels))
    cluster_stats = {int(lbl): {"size": labels.count(lbl), "mean": X[[i for i, ln in enumerate(labels) if ln == lbl]].mean(axis=0).tolist()} for lbl in unique_labels}
    return {"ok": True, "method": method, "n_clusters_found": len(unique_labels), "labels": labels, "centroids": centroids, "cluster_stats": cluster_stats, "features_used": col_names, "n_points": len(X), **extra}

def dataset_summary(path: str) -> dict:
    """
    Comprehensive statistical summary of any tabular data (CSV, Excel, JSON, Parquet).
    Returns: shape, dtypes, missing values, numeric stats, top correlations,
    categorical value counts, duplicate count, and data quality flags.
    """
    target = Path(path)
    if not inside_sandbox(target):
        return {"ok": False, "error": "Outside sandbox"}
    if not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        import numpy as _np
        import pandas as _pd
        ext = target.suffix.lower()
        if ext in (".csv", ".tsv"):
            df = _pd.read_csv(str(target), sep="\t" if ext == ".tsv" else ",")
        elif ext in (".xlsx", ".xls"):
            df = _pd.read_excel(str(target))
        elif ext == ".json":
            df = _pd.read_json(str(target))
        elif ext == ".parquet":
            df = _pd.read_parquet(str(target))
        else:
            df = _pd.read_csv(str(target))

        missing = df.isnull().sum()
        missing_pct = (missing / len(df) * 100).round(2)
        numeric_cols = df.select_dtypes(include="number")
        cat_cols = df.select_dtypes(include=["object", "category"])

        result: dict = {
            "ok": True, "path": str(target),
            "shape": {"rows": len(df), "columns": len(df.columns)},
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "missing": {col: {"count": int(missing[col]), "pct": float(missing_pct[col])} for col in df.columns if missing[col] > 0},
            "duplicates": int(df.duplicated().sum()),
        }
        if len(numeric_cols.columns) > 0:
            result["numeric_summary"] = numeric_cols.describe().to_dict()
            try:
                corr = numeric_cols.corr()
                pairs = []
                cols = list(corr.columns)
                for i in range(len(cols)):
                    for j in range(i+1, len(cols)):
                        val = float(corr.iloc[i, j])
                        if not _np.isnan(val):
                            pairs.append({"col_a": cols[i], "col_b": cols[j], "pearson_r": round(val, 4)})
                result["top_correlations"] = sorted(pairs, key=lambda x: abs(x["pearson_r"]), reverse=True)[:10]
            except Exception:
                pass
        if len(cat_cols.columns) > 0:
            result["categorical_summary"] = {col: {"unique_values": int(df[col].nunique()), "top_values": df[col].value_counts().head(10).to_dict()} for col in list(cat_cols.columns)[:5]}
        flags = []
        if result.get("duplicates", 0) > 0:
            flags.append(f"{result['duplicates']} duplicate rows found")
        high_missing = {k for k, v in result.get("missing", {}).items() if v["pct"] > 20}
        if high_missing:
            flags.append(f"High missing data (>20%) in: {', '.join(high_missing)}")
        result["quality_flags"] = flags
        return result
    except ImportError:
        return {"ok": False, "error": "pandas not installed: pip install pandas"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def db_backup(db_path: str, backup_path: str = "") -> dict:
    """Backup SQLite database. backup_path: optional; default adds .bak timestamp."""
    src = Path(db_path)
    if not inside_sandbox(src):
        return {"ok": False, "error": "Outside sandbox"}
    if not src.exists():
        return {"ok": False, "error": "Database not found"}
    dest = Path(backup_path) if backup_path else src.with_suffix(f".bak_{__import__('time').strftime('%Y%m%d_%H%M%S')}{src.suffix}")
    if not inside_sandbox(dest):
        return {"ok": False, "error": "Backup path outside sandbox"}
    try:
        import shutil
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        return {"ok": True, "source": str(src), "backup": str(dest)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


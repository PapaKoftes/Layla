# Config system (`runtime_safety`)

Sources: [`agent/runtime_safety.py`](../../agent/runtime_safety.py), [`agent/runtime_config.example.json`](../../agent/runtime_config.example.json).

## Config file location

- **`runtime_safety.CONFIG_FILE`**: **`LAYLA_DATA_DIR/runtime_config.json`** if **`LAYLA_DATA_DIR`** set, else **`agent/runtime_config.json`** ([`runtime_safety.py`](../../agent/runtime_safety.py)).

## Merge order

1. Large **`defaults`** dict embedded in **`load_config()`**.
2. JSON object from config file **`defaults.update(data)`** when parse succeeds.

## Cache

- TTL **2 seconds** (**`_CONFIG_CHECK_TTL`**) between stat/reload checks; **`invalidate_config_cache()`** clears cache after writes.

## Keys absent from defaults

- If a key is **not** in the embedded **`defaults`** dict and not present in the user JSON file, **`cfg.get("key")`** returns **`None`** / falsy for booleans unless code uses an explicit default in **`.get(..., default)`** at call site.

### `investigation_reuse_store_enabled`

- **Not** present in the **`defaults`** dict in [`runtime_safety.py`](../../agent/runtime_safety.py). Documented in [`runtime_config.example.json`](../../agent/runtime_config.example.json). Effective behavior: **`bool(cfg.get("investigation_reuse_store_enabled"))`** is false until set true in JSON ([`investigation_reuse.py`](../../agent/autonomous/investigation_reuse.py)).

## Autonomous Tier-0 (representative defaults in code)

See **`autonomous_*`**, **`autonomous_chroma_*`** keys in **`load_config`** defaults — authoritative values are in [`runtime_safety.py`](../../agent/runtime_safety.py) after patch.

## Full key list

- The canonical enumeration is the **`defaults = { ... }`** assignment inside **`load_config()`** in [`runtime_safety.py`](../../agent/runtime_safety.py) (multi-hundred keys).

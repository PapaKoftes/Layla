# Current limitations (documented behavior)

Sources: [`agent/main.py`](../../agent/main.py), [`agent/routers/autonomous.py`](../../agent/routers/autonomous.py).

## Remote access and `/autonomous/run`

- **`main._remote_allowed_paths`**: For **`remote_mode == "interactive"`**, an explicit list of paths is used when **`remote_allow_endpoints`** is empty. That list **does not** include **`/autonomous/run`** ([`main.py`](../../agent/main.py)).
- **`routers/autonomous._remote_allowed_paths`**: When **`remote_allow_endpoints`** is empty and **`remote_mode == "interactive"`**, this function returns **`[]`**, so path checks against an empty allowlist fail for non-localhost ([`autonomous.py`](../../agent/routers/autonomous.py)).

**Effect:** Remote clients typically need **`remote_allow_endpoints`** to explicitly allow **`/autonomous/run`** (and related paths) if Tier-0 HTTP autonomous is desired over the network. Localhost is exempt from remote middleware when implemented as in **`main.py`**.

## Narrative docs vs code

- Older markdown may describe routes or defaults that drifted. **`docs/system`** is the conflict-resolution layer per [`README`](README.md).

## Config keys only in example JSON

- Keys documented in **`runtime_config.example.json`** but absent from **`runtime_safety.load_config`** embedded defaults behave as falsy until set — see [`CONFIG_SYSTEM.md`](CONFIG_SYSTEM.md).

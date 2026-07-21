"""The example config is a SECOND source of defaults, and nothing reconciled it with the first.

`runtime_config.example.json` is copied forward into a live `runtime_config.json` by
`install/setup_existing_model.py`. Any key it sets EXPLICITLY therefore beats the shipped default in
`config_schema.EDITABLE_SCHEMA` / `runtime_safety`, because a code default only applies when the key
is ABSENT. So a fresh install does not get "the defaults" — it gets the example file.

This was not theoretical. P13-A2 raised the `convo_turns` default from 0 to 6 (the companion could
not see her own previous replies, so she repeated herself and lost the thread). The commit changed
the code default and shipped green — while the example config still said 0, so the fix reached
neither existing installs NOR new ones. The same defect class this codebase keeps producing: a
component correct in isolation, wired into a seam nobody tested.

Fixing that one key would leave the mechanism intact. This test pins the whole divergence set
instead: every key where the example deliberately differs from the shipped default must be listed
here WITH A REASON. A new silent divergence fails the gate, and so does a stale entry.

Keys owned by auto_tune are exempt: it overwrites them at every load_config(), so whatever the
example says is inert for those (n_ctx is the notable one).
"""
from __future__ import annotations

import json
from pathlib import Path

from config_schema import EDITABLE_SCHEMA
from services.infrastructure.auto_tune import PROFILE_KEYS

EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "runtime_config.example.json"

# key -> (example_value, why this divergence is intentional)
ALLOWED_DIVERGENCES: dict[str, tuple[object, str]] = {
    "elasticsearch_url": (
        "http://127.0.0.1:9200",
        "The example documents the URL FORMAT; the shipped default is empty (feature off). A fresh "
        "install pointing at a localhost ES that is not running fails closed to the normal search "
        "path, so this is documentation rather than a behaviour change.",
    ),
    "remote_api_key": (
        None,
        "JSON null vs the empty-string default — cosmetic, and both read as falsy at every use site. "
        "Left as null so the key is visibly present-but-unset rather than looking configured.",
    ),
    "deterministic_tool_routes_enabled": (
        True,
        "Deliberate: the example is a daily-driver profile and deterministic routing is the "
        "recommended operator setting. The schema default stays False so the feature is opt-in for "
        "anyone assembling a config from scratch.",
    ),
    "max_tool_calls": (
        20,
        "QUESTIONABLE, recorded rather than silently accepted: the schema default is 5 but the "
        "example ships 20, so a fresh install gets 4x the tool budget the schema advertises. Both "
        "values are safe (max_runtime_seconds still bounds a turn); the divergence is a product "
        "decision about how much rope a new install gets, and it should be made deliberately rather "
        "than inherited. See also research_max_tool_calls below.",
    ),
    "research_max_tool_calls": (
        40,
        "Research runs are explicitly long-horizon and the example doubles the budget for them. "
        "Consistent with max_tool_calls above being raised for the daily-driver profile.",
    ),
    "research_max_runtime_seconds": (
        900,
        "The example HALVES the research runtime (1800 -> 900). Opposite direction to the tool-call "
        "budget above, which is why it is listed separately: more calls, less wall-clock. Deliberate "
        "on weak hardware, where a 30-minute research turn is worse than an early stop.",
    ),
}


def _schema_defaults() -> dict[str, object]:
    return {e["key"]: e["default"] for e in EDITABLE_SCHEMA if "default" in e}


def _example() -> dict[str, object]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _actual_divergences() -> dict[str, tuple[object, object]]:
    """key -> (shipped_default, example_value) for non-auto_tune keys that disagree."""
    ex = _example()
    out: dict[str, tuple[object, object]] = {}
    for key, default in _schema_defaults().items():
        if key in PROFILE_KEYS:
            continue  # auto_tune overwrites these at every load; the example is inert for them
        if key in ex and ex[key] != default:
            out[key] = (default, ex[key])
    return out


def test_no_undeclared_divergence_between_example_config_and_shipped_defaults():
    diverged = _actual_divergences()
    undeclared = {k: v for k, v in diverged.items() if k not in ALLOWED_DIVERGENCES}
    assert not undeclared, (
        "runtime_config.example.json silently contradicts a shipped default. A fresh install is "
        "seeded from this file, so the code default never applies:\n"
        + "\n".join(f"  {k}: default={d!r} but example ships {e!r}" for k, (d, e) in sorted(undeclared.items()))
        + "\n\nEither change the example to match, or add the key to ALLOWED_DIVERGENCES with a reason."
    )


def test_declared_divergences_are_still_real():
    """A stale entry here is as bad as a missing one — it hides that the two sources re-converged."""
    diverged = _actual_divergences()
    stale = sorted(set(ALLOWED_DIVERGENCES) - set(diverged))
    assert not stale, (
        f"ALLOWED_DIVERGENCES lists keys that no longer diverge: {stale}. Remove them so this file "
        "keeps describing the config as it actually ships."
    )


def test_declared_divergence_values_have_not_drifted():
    diverged = _actual_divergences()
    for key, (expected_example, _reason) in ALLOWED_DIVERGENCES.items():
        if key not in diverged:
            continue
        _default, actual_example = diverged[key]
        assert actual_example == expected_example, (
            f"{key}: the example now ships {actual_example!r}, but the recorded justification was "
            f"written for {expected_example!r}. Re-justify the new value before changing this."
        )


def test_convo_turns_reaches_a_fresh_install():
    """The specific regression that motivated this file: she must be able to see the conversation.

    convo_turns is NOT auto_tune-owned, so an explicit 0 in the example config would beat the
    shipped default of 6 and every new install would ship with the companion unable to read her own
    previous replies.
    """
    assert "convo_turns" not in PROFILE_KEYS, "if auto_tune takes ownership, this test's premise dies"
    example_value = _example().get("convo_turns")
    assert example_value is not None, "convo_turns absent from the example: the code default applies, fine"
    assert example_value >= 2, (
        f"runtime_config.example.json ships convo_turns={example_value}. At 0 the model receives NO "
        "conversation history at all and cannot see its own previous replies; below 2 it cannot see "
        "its own last reply plus the user's."
    )

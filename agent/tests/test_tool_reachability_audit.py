"""Static tool-reachability + signature + effect-verifier audit (PLAN item 24).

WHY THIS EXISTS
    The ~200 registered tools are each unit-tested in isolation, but the failure modes that
    made tool-calling *silently* broken before were never structural failures of one tool — they
    were failures of the plumbing AROUND every tool, invisible to a per-tool test and to a
    `len(TOOLS)` count:

      1. THE `functools.wraps` REGRESSION. `_wrap_tool_with_metrics` wraps every tool for latency
         metrics. When the `@functools.wraps(fn)` line was once missing, the wrapper replaced
         EVERY tool's signature with `(*args, **kwargs)` and nulled every `__doc__`. The registry
         still held N callables, `len(TOOLS)` still passed, `list_tools` still enumerated them —
         but there was no static contract for the decision layer to validate the model's args
         against, so args were discarded and `math_eval` raised on every input. A count test
         cannot see this; a signature test can.

      2. PERMANENTLY-UNREACHABLE TOOLS. A tool can be registered yet offered to the model under NO
         config/goal — filtered out permanently by the router's allowlist logic. Such a tool is
         dead weight the model can never pick. This must be distinguished from a tool that is
         merely DEP-GATED (its optional backing library is absent in this environment) — that one
         is *legitimately* withheld here and returns the moment the lib is installed.

      3. THE MISSING-VERIFIER BLIND SPOT. `deterministic_verify_tool_result` re-checks a tool's
         claimed success against reality (file exists after write, returncode == 0, …). Only a
         subset of tools have such a verifier; the model-driven harness that runs later needs to
         know WHICH, because a tool with no verifier can report `ok: True` with nothing to catch a
         lie (the empty-sandbox class where file tools were 0/13 but reported success).

    This test IS the artifact: it reads the LIVE registry (never a hardcoded list), computes the
    audit with stdlib `inspect` + the REAL production gating functions, PRINTS a summary, and:

        PASSES iff  0 signature-erased tools  AND  0 permanently-unreachable tools.
        PRINTS      registered / offered-in-env / dep-gated / has-verifier / no-verifier counts
                    (informational — a missing verifier is not a failure, it is a fact the driven
                    harness consumes).

    MODEL-FREE by construction: every function used below is pure/static (signature introspection,
    the allowlist resolver under `skip_intent_filter`, the dependency/feature drop filters, and the
    deterministic verifier probed with a synthetic result). No inference, so it runs in normal CI.
"""
from __future__ import annotations

import inspect
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from layla.tools.registry import TOOL_COUNT_THRESHOLD, TOOLS  # noqa: E402
from services.agent.llm_decision import (  # noqa: E402
    _drop_disabled_feature_tools,
    _drop_missing_dependency_tools,
    _module_installed,
)
from services.tools.tool_output_validator import deterministic_verify_tool_result  # noqa: E402
from services.tools.tool_policy import resolve_effective_tools_for_route  # noqa: E402

# `reason` is a virtual action (reply to the user), not a registry tool; every allowlist path
# re-adds it, so it is excluded before comparing against registered tool names.
_VIRTUAL = frozenset({"reason"})

# A neutral goal. Reachability is proved with `skip_intent_filter=True` (the config a real operator
# gets from `tool_routing_enabled=False`), under which the offered set does not depend on the goal
# text at all — this string exists only to satisfy the resolver's signature.
_GENERIC_GOAL = "inspect the workspace and answer the question"

# The verifier probe feeds a synthetic minimal success result. A tool WITH a verifier runs its
# branch and returns some reason other than this sentinel (even a "missing_path" failure proves a
# verifier exists); a tool WITHOUT one falls through to the default and returns exactly this.
_NO_VERIFIER_SENTINEL = "no_verifier"


def _signature_is_erased(fn: object) -> tuple[bool, str]:
    """Detect the `functools.wraps`-regression fingerprint: a callable whose signature carries NO
    named contract, only `*args`/`**kwargs`.

    Returns ``(is_erased, signature_repr)``.

    `inspect.signature` follows `__wrapped__` (set by `functools.wraps`), so with the decorator
    intact it reports the ORIGINAL tool's real parameters; with the decorator missing it reports the
    wrapper's own bare `(*args, **kwargs)`. A genuine no-argument tool (empty signature) is NOT
    erased — it has a complete, if empty, contract. A tool that mixes a named parameter with
    `*args`/`**kwargs` is NOT erased either; only a purely-variadic signature is the fingerprint.
    """
    if not callable(fn):
        return True, "<not-callable>"
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:  # un-introspectable == no static contract at all
        return True, f"<no-signature: {exc}>"
    params = list(sig.parameters.values())
    if not params:
        return False, str(sig)  # legitimate no-arg tool
    named = [
        p for p in params
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    has_variadic = any(
        p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for p in params
    )
    return (has_variadic and not named), str(sig)


@dataclass
class ToolAuditReport:
    registered: list[str]
    signature_erased: list[tuple[str, str]]
    offered_base: list[str]
    permanently_unreachable: list[str]
    dep_gated: dict[str, str]
    feature_gated: list[str]
    offered_in_env: list[str]
    has_verifier: list[str]
    no_verifier: list[str]

    def summary(self) -> str:
        lines = [
            "",
            "=" * 78,
            "TOOL REACHABILITY / SIGNATURE / VERIFIER AUDIT (model-free, PLAN item 24)",
            "=" * 78,
            f"  registered ............. {len(self.registered)}",
            f"  offered (allowlist) .... {len(self.offered_base)}   (structurally reachable)",
            f"  offered in THIS env .... {len(self.offered_in_env)}   (deps present + feature enabled)",
            f"  dep-gated .............. {len(self.dep_gated)}   (optional lib absent -- legitimately withheld here)",
            f"  feature-gated .......... {len(self.feature_gated)}   (feature flag off under default config)",
            f"  has effect-verifier .... {len(self.has_verifier)}",
            f"  no effect-verifier ..... {len(self.no_verifier)}   (driven harness cannot deterministically re-check these)",
            "-" * 78,
            f"  signature-erased (BUG) . {len(self.signature_erased)}",
            f"  permanently-unreachable  {len(self.permanently_unreachable)}  (BUG)",
            "-" * 78,
        ]
        if self.dep_gated:
            lines.append("  dep-gated tools (name -> required module):")
            for name in sorted(self.dep_gated):
                lines.append(f"      {name} -> {self.dep_gated[name]}")
        if self.feature_gated:
            lines.append("  feature-gated tools: " + ", ".join(self.feature_gated))
        if self.has_verifier:
            lines.append("  tools WITH a verifier: " + ", ".join(sorted(self.has_verifier)))
        if self.signature_erased:
            lines.append("  SIGNATURE-ERASED:")
            for name, rep in self.signature_erased:
                lines.append(f"      {name}: {rep}")
        if self.permanently_unreachable:
            lines.append("  PERMANENTLY-UNREACHABLE: " + ", ".join(self.permanently_unreachable))
        lines.append("=" * 78)
        return "\n".join(lines)


def _build_report() -> ToolAuditReport:
    registered = sorted(TOOLS.keys())

    # (1) Signature erasure — guards the functools.wraps regression.
    signature_erased = []
    for name in registered:
        bad, rep = _signature_is_erased(TOOLS[name].get("fn") if isinstance(TOOLS[name], dict) else None)
        if bad:
            signature_erased.append((name, rep))

    # (2) Reachability via the REAL router allowlist logic under the most permissive config a real
    # operator can set (full profile, routing off => skip_intent_filter). This resolver does NOT
    # apply the dependency/feature drops (those live in llm_decision and run afterwards), so its
    # output is the pure STRUCTURAL reachable set — exactly what "permanently unreachable" must be
    # measured against, independent of which optional libs happen to be installed here.
    offered_base = set(
        resolve_effective_tools_for_route(
            {"tools_profile": "full"}, None, _GENERIC_GOAL, TOOLS, skip_intent_filter=True,
        )
    ) - _VIRTUAL
    permanently_unreachable = sorted(set(registered) - offered_base)

    # (3) Dependency gating — a tool whose `requires` module is not importable in this env. Reuses
    # the production predicate so the audit agrees with what the model is actually shown.
    dep_gated: dict[str, str] = {}
    for name in registered:
        meta = TOOLS[name]
        req = meta.get("requires") if isinstance(meta, dict) else None
        if req and not _module_installed(str(req)):
            dep_gated[name] = str(req)

    # (4) Feature gating under the as-shipped DEFAULT config (empty cfg): informational. Reuses the
    # production drop filter. `offered_in_env` = structurally reachable AND deps present AND feature
    # enabled — the set the model would actually be offered on this box, right now.
    after_feature = _drop_disabled_feature_tools(set(offered_base), TOOLS, {})
    feature_gated = sorted(offered_base - after_feature)
    after_dep = _drop_missing_dependency_tools(set(offered_base), TOOLS)
    offered_in_env = sorted(offered_base & after_dep & after_feature)

    # (5) Effect verifiers — probe the real deterministic verifier with a synthetic success.
    with tempfile.TemporaryDirectory() as tmp:
        has_verifier, no_verifier = [], []
        for name in registered:
            vr = deterministic_verify_tool_result(name, {"ok": True}, workspace_root=tmp) or {}
            if vr.get("reason") == _NO_VERIFIER_SENTINEL:
                no_verifier.append(name)
            else:
                has_verifier.append(name)

    return ToolAuditReport(
        registered=registered,
        signature_erased=signature_erased,
        offered_base=sorted(offered_base),
        permanently_unreachable=permanently_unreachable,
        dep_gated=dep_gated,
        feature_gated=feature_gated,
        offered_in_env=offered_in_env,
        has_verifier=has_verifier,
        no_verifier=no_verifier,
    )


# Computed once at import; the audit is cheap (<1s) and pure, so a module-level singleton keeps the
# summary and every assertion looking at the same snapshot.
_REPORT = _build_report()


def test_audit_summary_and_hard_gates():
    """The artifact. Prints the full summary, then enforces the two hard gates.

    PASSES iff there are zero signature-erased tools AND zero permanently-unreachable tools. The
    verifier / dep-gated / feature-gated counts are printed but never fail the build — they are
    ground truth for the model-driven harness, not a quality bar.
    """
    print(_REPORT.summary())

    assert not _REPORT.signature_erased, (
        f"{len(_REPORT.signature_erased)} tool(s) have a signature reduced to (*args, **kwargs)-only: "
        f"{[n for n, _ in _REPORT.signature_erased]}. This is the functools.wraps regression — the "
        f"metrics wrapper is discarding the real parameter contract, so the decision layer has nothing "
        f"to validate the model's args against and will silently drop them. Restore @functools.wraps in "
        f"_wrap_tool_with_metrics (registry.py)."
    )
    assert not _REPORT.permanently_unreachable, (
        f"{len(_REPORT.permanently_unreachable)} registered tool(s) are offered under NO config/goal: "
        f"{_REPORT.permanently_unreachable}. They are dead weight the model can never pick. This is a "
        f"reachability BUG in the router allowlist logic (tool_policy.resolve_effective_tools_for_route) "
        f"— NOT the same as a dep-gated tool, which stays in the allowlist and returns when its library "
        f"is installed."
    )


def test_registry_loaded_and_non_trivial():
    """A guard against a broken registry import masquerading as a clean audit: if the registry failed
    to assemble, every downstream set would be empty and the hard gates would pass vacuously."""
    assert len(_REPORT.registered) >= TOOL_COUNT_THRESHOLD, (
        f"registry has only {len(_REPORT.registered)} tools (< {TOOL_COUNT_THRESHOLD}); it likely "
        f"failed to assemble, which would make every reachability assertion pass vacuously."
    )


def test_every_tool_has_an_introspectable_signature():
    """Item 1, stated positively: every registered tool must expose a real parameter contract (or a
    genuine empty one). This is the exact property the functools.wraps regression destroyed."""
    assert not _REPORT.signature_erased, (
        "signature-erased tools: " + ", ".join(f"{n} {r}" for n, r in _REPORT.signature_erased)
    )


def test_dep_gated_tools_are_legitimately_gated_not_permanently_unreachable():
    """Item 2's distinction, asserted directly: a dep-gated tool is a LEGITIMATE absence, not a bug.

    Each one must (a) carry a real non-empty `requires` string, (b) still sit in the structural
    allowlist (so it returns the instant its library is installed), and (c) therefore NOT appear in
    the permanently-unreachable set. If a dep-gated tool ever fell out of the allowlist, its absence
    would no longer be reversible by installing a package — that would be the bug this separates out.
    """
    base = set(_REPORT.offered_base)
    unreachable = set(_REPORT.permanently_unreachable)
    for name, req in _REPORT.dep_gated.items():
        assert req, f"{name} is dep-gated but its `requires` is empty — cannot be legitimately gated"
        assert name in base, (
            f"{name} is dep-gated on {req!r} yet absent from the structural allowlist — its absence is "
            f"NOT merely a missing optional lib, so it would not return on install. That is a real bug."
        )
        assert name not in unreachable, f"{name} classified as BOTH dep-gated and permanently-unreachable"


def test_verifier_partition_is_total_and_disjoint():
    """The has-verifier / no-verifier split the driven harness relies on must cover every registered
    tool exactly once — no tool silently uncategorised, none double-counted."""
    has = set(_REPORT.has_verifier)
    no = set(_REPORT.no_verifier)
    assert has.isdisjoint(no), f"tools in both verifier buckets: {sorted(has & no)}"
    assert has | no == set(_REPORT.registered), (
        f"verifier partition does not cover the registry; missing: "
        f"{sorted(set(_REPORT.registered) - (has | no))}"
    )

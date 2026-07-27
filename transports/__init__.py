"""Chat transports for Layla: Slack, Telegram (Discord lives in discord_bot/).

Each transport is an OPTIONAL, off-by-default, separately launched process that
drives its inbound turns through the shared ``TransportAdapter`` — one security
policy (allowlist/pairing) and one hard rule: transport turns never get
allow_write / allow_run. See ``transports/README.md``.
"""
from transports.base import (
    InboundResult,
    TransportAdapter,
    call_layla_async,
    call_layla_sync,
    check_transport_inbound,
    get_inbound_transport_security,
)

__all__ = [
    "InboundResult",
    "TransportAdapter",
    "call_layla_async",
    "call_layla_sync",
    "check_transport_inbound",
    "get_inbound_transport_security",
]

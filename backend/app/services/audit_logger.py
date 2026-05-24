"""Audit logger stub.

Provides a minimal interface for recording audit events.
"""
from typing import Dict, Any


def record_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Record an audit event. Stub implementation logs to stdout for now."""
    print(f"AUDIT: {event_type} - {payload}")

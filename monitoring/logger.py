"""Structured logging setup with rotation and audit trail."""
from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_file: str = "logs/trading_bot.log", level: str = "INFO") -> logging.Logger:
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("trade_v2")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if root.handlers:
        return root

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(name)-22s | %(levelname)-7s | %(message)s")
    )
    root.addHandler(file_handler)
    return root


class AuditLog:
    """Persist audit events to the state store with secrets redacted."""

    SENSITIVE_KEYS = {"api_key", "api_secret", "password", "token", "secret", "webhook_url"}

    def __init__(self, store):
        self.store = store

    def _redact(self, details: dict) -> dict:
        clean = {}
        for key, value in (details or {}).items():
            if any(s in str(key).lower() for s in self.SENSITIVE_KEYS):
                clean[key] = "[redacted]"
            else:
                clean[key] = value
        return clean

    def record(self, event_type: str, details: dict | None = None) -> None:
        try:
            self.store.append_event(event_type, self._redact(details or {}))
        except Exception:
            logging.getLogger("trade_v2.audit").exception("Could not write audit event")

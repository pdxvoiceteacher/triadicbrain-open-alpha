"""Fail-closed error types for the private totality convergence layer."""

from __future__ import annotations


class TotalityError(RuntimeError):
    """Base error carrying a stable machine-readable reason code."""


class ValidationError(TotalityError, ValueError):
    """An external artifact failed strict validation."""


class OperationalError(TotalityError):
    """A local operation could not be completed safely."""

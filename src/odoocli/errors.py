"""Typed exceptions for odoocli, classified from Odoo JSON-RPC error payloads."""

from __future__ import annotations

from typing import Any


class OdooError(Exception):
    """Base error. ``exit_code`` is what the CLI returns for this class."""

    exit_code: int = 1
    default_code: str = "odoo_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.code = code or self.default_code
        self.data = data
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            # Keep what helps a caller decide; drop the server traceback.
            odoo = {k: v for k, v in self.data.items() if k in ("name", "message", "arguments")}
            if odoo:
                out["odoo"] = odoo
        return out


class OdooConnectionError(OdooError):
    """Cannot reach or talk JSON-RPC with the server (network, HTTP status, bad URL)."""

    exit_code = 3
    default_code = "connection_error"


class OdooAuthError(OdooError):
    """Credentials rejected."""

    exit_code = 3
    default_code = "auth_failed"


class OdooAccessError(OdooError):
    """Authenticated but not allowed (ACL, record rule)."""

    default_code = "access_error"


class OdooValidationError(OdooError):
    """Business rule rejected the call (ValidationError, UserError)."""

    default_code = "validation_error"


class OdooMissingError(OdooError):
    """Record does not exist."""

    default_code = "missing_record"


class OdooRefusedError(OdooError):
    """The CLI itself refused the operation (guards), Odoo was never called."""

    exit_code = 4
    default_code = "refused"


class OdooUsageError(OdooError):
    """Bad arguments that the CLI can detect before calling Odoo."""

    exit_code = 2
    default_code = "usage_error"


_BY_EXCEPTION_NAME: dict[str, type[OdooError]] = {
    "odoo.exceptions.AccessDenied": OdooAuthError,
    "odoo.exceptions.AccessError": OdooAccessError,
    "odoo.exceptions.ValidationError": OdooValidationError,
    "odoo.exceptions.UserError": OdooValidationError,
    "odoo.exceptions.RedirectWarning": OdooValidationError,
    "odoo.exceptions.MissingError": OdooMissingError,
}


def classify_rpc_error(error: dict[str, Any]) -> OdooError:
    """Map the ``error`` object of a JSON-RPC response to a typed exception."""
    data = error.get("data") or {}
    name = str(data.get("name", ""))
    message = str(data.get("message") or error.get("message") or "Unknown Odoo error")
    cls = _BY_EXCEPTION_NAME.get(name, OdooError)
    code = None if cls is not OdooError else "rpc_error"
    return cls(message, code=code, data=data or None)

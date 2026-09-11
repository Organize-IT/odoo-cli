"""odoocli: Odoo JSON-RPC client and CLI built for AI agents and scripts."""

from odoocli._version import __version__
from odoocli.client import AsyncOdooClient
from odoocli.errors import (
    OdooAccessError,
    OdooAuthError,
    OdooConnectionError,
    OdooError,
    OdooMissingError,
    OdooRefusedError,
    OdooRepairedError,
    OdooUsageError,
    OdooValidationError,
)
from odoocli.sync import OdooClient

__all__ = [
    "AsyncOdooClient",
    "OdooAccessError",
    "OdooAuthError",
    "OdooClient",
    "OdooConnectionError",
    "OdooError",
    "OdooMissingError",
    "OdooRefusedError",
    "OdooRepairedError",
    "OdooUsageError",
    "OdooValidationError",
    "__version__",
]

from typing import Any

import pytest

from odoocli.errors import (
    OdooAccessError,
    OdooAuthError,
    OdooError,
    OdooMissingError,
    OdooRefusedError,
    OdooValidationError,
    classify_rpc_error,
)


def rpc(name: str, message: str = "boom", **extra: Any) -> dict[str, Any]:
    return {
        "code": 200,
        "message": "Odoo Server Error",
        "data": {"name": name, "message": message, **extra},
    }


@pytest.mark.parametrize(
    ("name", "cls"),
    [
        ("odoo.exceptions.AccessDenied", OdooAuthError),
        ("odoo.exceptions.AccessError", OdooAccessError),
        ("odoo.exceptions.ValidationError", OdooValidationError),
        ("odoo.exceptions.UserError", OdooValidationError),
        ("odoo.exceptions.MissingError", OdooMissingError),
        ("builtins.ValueError", OdooError),
    ],
)
def test_classify_by_exception_name(name: str, cls: type[OdooError]) -> None:
    err = classify_rpc_error(rpc(name, "Invalid field 'foo'"))
    assert type(err) is cls
    assert err.message == "Invalid field 'foo'"
    assert err.data is not None and err.data["name"] == name


def test_classify_without_data_uses_top_level_message() -> None:
    err = classify_rpc_error({"code": 100, "message": "Odoo Session Expired"})
    assert type(err) is OdooError
    assert err.message == "Odoo Session Expired"
    assert err.code == "rpc_error"


def test_to_dict_and_exit_codes() -> None:
    err = OdooRefusedError("writes are disabled", code="writes_disabled")
    assert err.exit_code == 4
    assert err.to_dict() == {"code": "writes_disabled", "message": "writes are disabled"}
    assert OdooAuthError("x").exit_code == 3
    assert OdooValidationError("x").exit_code == 1


def test_to_dict_includes_odoo_payload_without_debug() -> None:
    err = classify_rpc_error(
        rpc("odoo.exceptions.UserError", "nope", debug="Traceback...", arguments=["nope"])
    )
    d = err.to_dict()
    assert d["odoo"] == {
        "name": "odoo.exceptions.UserError",
        "message": "nope",
        "arguments": ["nope"],
    }
    assert "debug" not in d["odoo"]

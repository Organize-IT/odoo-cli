from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from odoocli import OdooClient

REQUIRED = ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY")


@pytest.fixture(scope="session")
def live() -> Iterator[OdooClient]:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        pytest.skip(f"integration needs {', '.join(missing)}")
    with OdooClient(
        os.environ["ODOO_URL"],
        os.environ["ODOO_DB"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_API_KEY"],
    ) as client:
        yield client

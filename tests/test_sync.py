from odoocli import OdooClient
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo


def test_sync_client_roundtrip(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [{"id": 1, "name": "Acme"}])
    fake_odoo.on("res.partner", "search_count", 1)
    with OdooClient(BASE_URL, DB, LOGIN, KEY) as c:
        assert c.version()["server_version"] == "17.0"
        assert c.authenticate() == 7
        assert c.search_read("res.partner", [], fields=["name"]) == [{"id": 1, "name": "Acme"}]
        assert c.search_count("res.partner") == 1
        assert c.uid == 7


def test_sync_client_close_is_idempotent(fake_odoo: FakeOdoo) -> None:
    c = OdooClient(BASE_URL, DB, LOGIN, KEY)
    c.version()
    c.close()
    c.close()


def test_sync_search_and_context(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search", [5])
    with OdooClient(BASE_URL, DB, LOGIN, KEY, context={"lang": "fr_BE"}) as c:
        c.context["active_test"] = False
        assert c.search("res.partner", []) == [5]
    assert fake_odoo.calls[0][3]["context"] == {"lang": "fr_BE", "active_test": False}

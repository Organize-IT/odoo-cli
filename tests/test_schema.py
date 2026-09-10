from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from odoocli import schema
from odoocli.client import AsyncOdooClient
from odoocli.errors import OdooUsageError
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo, RpcFailure

PARTNER_FIELDS: dict[str, Any] = {
    "id": {"type": "integer", "store": True},
    "name": {"type": "char", "store": True},
    "email": {"type": "char", "store": True},
    "mobile": {"type": "char", "store": True},
    "phone": {"type": "char", "store": True},
    "country_id": {"type": "many2one", "relation": "res.country", "store": True},
    "credit": {"type": "monetary", "store": False, "searchable": False, "sortable": False},
}
COUNTRY_FIELDS: dict[str, Any] = {
    "id": {"type": "integer", "store": True},
    "code": {"type": "char", "store": True},
    "name": {"type": "char", "store": True},
}


def serve_schema(fake: FakeOdoo) -> None:
    fake.on("res.partner", "fields_get", PARTNER_FIELDS)
    fake.on("res.country", "fields_get", COUNTRY_FIELDS)


def store(tmp_path: Path, **env: str) -> schema.SchemaStore:
    return schema.SchemaStore(
        BASE_URL, DB, env={"ODOO_CACHE_DIR": str(tmp_path), **env}, enabled=True
    )


def client() -> AsyncOdooClient:
    return AsyncOdooClient(BASE_URL, DB, LOGIN, KEY)


# ----- suggestions -----


def test_suggest_prefers_close_spelling() -> None:
    assert schema.suggest("mobil", sorted(PARTNER_FIELDS))[0] == "mobile"


def test_suggest_falls_back_to_substring() -> None:
    assert "country_id" in schema.suggest("country", sorted(PARTNER_FIELDS))


def test_suggest_returns_nothing_for_gibberish() -> None:
    assert schema.suggest("zzzzzzzz", sorted(PARTNER_FIELDS)) == []


# ----- cache -----


def test_cache_file_is_per_connection(tmp_path: Path) -> None:
    env = {"ODOO_CACHE_DIR": str(tmp_path)}
    assert schema.cache_file(env, BASE_URL, "a") != schema.cache_file(env, BASE_URL, "b")


async def test_fields_are_fetched_once_per_process(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    st = store(tmp_path)
    async with client() as c:
        assert await st.fields(c, "res.partner") == PARTNER_FIELDS
        await st.fields(c, "res.partner")
    assert [call[:2] for call in fake_odoo.calls] == [("res.partner", "fields_get")]


async def test_schema_survives_in_a_new_store(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        first = store(tmp_path)
        await first.fields(c, "res.partner")
        first.flush()
        second = store(tmp_path)
        assert await second.fields(c, "res.partner") == PARTNER_FIELDS
    assert len(fake_odoo.calls) == 1


async def test_expired_entries_are_refetched(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        first = store(tmp_path)
        await first.fields(c, "res.partner")
        first.flush()
        path = schema.cache_file({"ODOO_CACHE_DIR": str(tmp_path)}, BASE_URL, DB)
        raw = json.loads(path.read_text())
        raw["models"]["res.partner"]["fetched_at"] = time.time() - 10_000
        path.write_text(json.dumps(raw))
        await store(tmp_path, ODOO_SCHEMA_TTL="60").fields(c, "res.partner")
    assert len(fake_odoo.calls) == 2


async def test_ttl_zero_disables_the_disk_cache(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        st = store(tmp_path, ODOO_SCHEMA_TTL="0")
        await st.fields(c, "res.partner")
        st.flush()
    assert not list(tmp_path.glob("*.json"))


async def test_unreadable_model_yields_no_opinion(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    def refuse(_a: list[Any], _k: dict[str, Any]) -> Any:
        raise RpcFailure("odoo.exceptions.AccessError", "not allowed")

    fake_odoo.on("res.partner", "fields_get", refuse)
    async with client() as c:
        assert await store(tmp_path).fields(c, "res.partner") is None


async def test_disabled_store_never_calls_odoo(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    st = schema.SchemaStore(BASE_URL, DB, env={"ODOO_CACHE_DIR": str(tmp_path)}, enabled=False)
    async with client() as c:
        assert await st.fields(c, "res.partner") is None
    assert fake_odoo.calls == []


# ----- path resolution -----


async def test_dotted_path_follows_the_relation(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        found, problem = await schema.resolve_path(
            store(tmp_path), c, "res.partner", "country_id.code"
        )
    assert problem is None and found is not None and found["type"] == "char"


async def test_unknown_hop_is_reported_on_the_related_model(
    fake_odoo: FakeOdoo, tmp_path: Path
) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        _, problem = await schema.resolve_path(store(tmp_path), c, "res.partner", "country_id.cod")
    assert problem is not None
    assert problem.model == "res.country" and problem.unknown == "cod"
    assert problem.suggestions[0] == "code"


async def test_traversing_a_scalar_is_left_to_the_server(
    fake_odoo: FakeOdoo, tmp_path: Path
) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        found, problem = await schema.resolve_path(store(tmp_path), c, "res.partner", "name.x")
    assert (found, problem) == (None, None)


# ----- check -----


async def test_check_flags_unknown_field_in_domain(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        report = await schema.check(store(tmp_path), c, "res.partner", domain=[["mobil", "=", "x"]])
    assert [p.unknown for p in report.problems] == ["mobil"]
    with pytest.raises(OdooUsageError) as excinfo:
        report.raise_if_unknown()
    assert excinfo.value.code == "unknown_field"
    assert "Did you mean 'mobile'?" in excinfo.value.message


async def test_check_accepts_a_valid_query(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        report = await schema.check(
            store(tmp_path),
            c,
            "res.partner",
            fields=["name", "country_id"],
            domain=[["country_id.code", "=", "BE"]],
            order="name desc, id",
        )
    assert report.problems == [] and report.not_stored == []


async def test_check_reports_unstored_fields_used_in_a_filter(
    fake_odoo: FakeOdoo, tmp_path: Path
) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        report = await schema.check(
            store(tmp_path), c, "res.partner", fields=["credit"], domain=[["credit", ">", 0]]
        )
    assert report.problems == []
    assert report.not_stored == [("credit", "domain")]


async def test_check_validates_write_values(fake_odoo: FakeOdoo, tmp_path: Path) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        report = await schema.check(store(tmp_path), c, "res.partner", values=["nam", "email"])
    assert [p.unknown for p in report.problems] == ["nam"]


async def test_check_ignores_expressions_it_cannot_parse(
    fake_odoo: FakeOdoo, tmp_path: Path
) -> None:
    serve_schema(fake_odoo)
    async with client() as c:
        report = await schema.check(store(tmp_path), c, "res.partner", domain=[[1, "=", 1]])
    assert report.problems == []


def test_problem_sentence_mentions_the_path() -> None:
    problem = schema.FieldProblem("res.country", "country_id.cod", "cod", ["code"])
    assert problem.sentence() == (
        "res.country has no field 'cod' (in 'country_id.cod'). Did you mean 'code'?"
    )

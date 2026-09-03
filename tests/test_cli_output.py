import json

from odoocli.cli.output import detect_format, render
from odoocli.cli.values import parse_ids, parse_kv, split_fields

ROWS = [{"id": 1, "name": "Acme", "user_id": [3, "Bob"], "active": True, "email": False}]


def test_detect_format() -> None:
    assert detect_format(None, True) == "table"
    assert detect_format(None, False) == "json"
    assert detect_format("csv", True) == "csv"


def test_json_is_raw_and_stable() -> None:
    assert json.loads(render(ROWS, "json")) == ROWS
    assert render(42, "json") == "42"


def test_jsonl_one_line_per_record() -> None:
    out = render(ROWS + [{"id": 2}], "jsonl").splitlines()
    assert [json.loads(line) for line in out] == ROWS + [{"id": 2}]
    assert render({"a": 1}, "jsonl") == '{"a": 1}'


def test_csv_flattens_nested_as_json() -> None:
    lines = render(ROWS, "csv").splitlines()
    assert lines[0] == "id,name,user_id,active,email"
    assert lines[1] == '1,Acme,"[3, ""Bob""]",True,False'


def test_table_humanises_m2o_and_hides_false() -> None:
    out = render(ROWS, "table")
    assert "Bob (#3)" in out and "Acme" in out
    assert "False" not in out


def test_table_scalar_falls_back_to_json() -> None:
    assert render(12, "table") == "12"
    assert render([], "table") == ""


def test_table_rows_override_for_non_list_data() -> None:
    out = render({"x": {"type": "char"}}, "table", table_rows=[{"field": "x", "type": "char"}])
    assert "char" in out


def test_values_helpers() -> None:
    assert parse_ids(["1,2", "3"]) == [1, 2, 3]
    assert parse_kv(["name=Acme", "is_company=true", "tag_ids=[1,2]", "ref='007'"]) == {
        "name": "Acme",
        "is_company": True,
        "tag_ids": [1, 2],
        "ref": "007",
    }
    assert split_fields("a, b,c") == ["a", "b", "c"]
    assert split_fields(None) is None

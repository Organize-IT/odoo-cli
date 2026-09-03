from odoocli.security import is_read_safe_method, is_sensitive_model, redact


def test_sensitive_models() -> None:
    assert is_sensitive_model("ir.config_parameter")
    assert is_sensitive_model("res.users.apikeys")
    assert is_sensitive_model("ir.mail_server")
    assert not is_sensitive_model("res.partner")
    assert not is_sensitive_model("ir.model")


def test_redact_walks_lists_and_dicts() -> None:
    data = [{"id": 1, "smtp_pass": "x", "child": {"api_key": "k", "name": "n"}, "tags": ["a"]}]
    assert redact(data) == [
        {
            "id": 1,
            "smtp_pass": "[redacted]",
            "child": {"api_key": "[redacted]", "name": "n"},
            "tags": ["a"],
        }
    ]
    assert redact(42) == 42


def test_read_safe_methods() -> None:
    assert is_read_safe_method("search_read")
    assert is_read_safe_method("name_search")
    assert is_read_safe_method("read_group")
    assert not is_read_safe_method("action_confirm")
    assert not is_read_safe_method("write")

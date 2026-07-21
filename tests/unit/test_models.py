from telegram_cursor_agent.models import DEFAULT_MODEL_ALIASES, resolve_model_input


def test_resolve_model_input_expands_aliases() -> None:
    assert resolve_model_input("s5", DEFAULT_MODEL_ALIASES) == "claude-sonnet-5"
    assert resolve_model_input("c25", DEFAULT_MODEL_ALIASES) == "composer-2.5"
    assert resolve_model_input("op", DEFAULT_MODEL_ALIASES) == "claude-opus-4-8"


def test_resolve_model_input_passes_through_full_ids() -> None:
    assert resolve_model_input("claude-sonnet-5", DEFAULT_MODEL_ALIASES) == "claude-sonnet-5"


def test_resolve_model_input_is_case_insensitive() -> None:
    assert resolve_model_input("S5", DEFAULT_MODEL_ALIASES) == "claude-sonnet-5"

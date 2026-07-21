from pathlib import Path

from telegram_cursor_agent.config import DEFAULT_SESSION_HEADER_TEMPLATE, load_config
from telegram_cursor_agent.models import DEFAULT_MODEL_ALIASES


def test_load_config_parses_all_fields(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
        workspace_path = "~/projects/example"
        allowed_sender_ids = [111, 222]
        default_model = "claude-sonnet-5"
        default_perms_mode = "standard"
        perms_dir = "./perms"
        session_store_dir = "./data"
        session_header_template = "mode={mode}"
        """)

    config = load_config(config_file)

    assert config.workspace_path == Path("~/projects/example").expanduser()
    assert config.allowed_sender_ids == frozenset({111, 222})
    assert config.default_model == "claude-sonnet-5"
    assert config.default_perms_mode == "standard"
    assert config.perms_dir == Path("./perms")
    assert config.session_store_dir == Path("./data")
    assert config.session_header_template == "mode={mode}"
    assert "s5" in config.model_aliases


def test_load_config_defaults_perms_dir_when_absent(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
        workspace_path = "/tmp/example"
        allowed_sender_ids = [111]
        default_model = "claude-sonnet-5"
        default_perms_mode = "readonly"
        """)

    config = load_config(config_file)

    assert config.perms_dir == Path("./perms")
    assert config.session_store_dir == Path("./data")
    assert config.session_header_template == DEFAULT_SESSION_HEADER_TEMPLATE
    assert config.model_aliases["s5"] == DEFAULT_MODEL_ALIASES["s5"]


def test_load_config_empty_header_template_disables_header(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("""
        workspace_path = "/tmp/example"
        allowed_sender_ids = [111]
        default_model = "claude-sonnet-5"
        default_perms_mode = "standard"
        session_header_template = ""
        """)

    config = load_config(config_file)

    assert config.session_header_template is None

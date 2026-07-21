import tomllib
from pathlib import Path

import telegram_cursor_agent


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(telegram_cursor_agent.__version__, str)
    assert telegram_cursor_agent.__version__


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert telegram_cursor_agent.__version__ == pyproject["project"]["version"]

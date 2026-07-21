"""Model ID aliases — short Telegram-friendly names resolved before SDK validation."""

from __future__ import annotations

# ponytail: static defaults; config [model_aliases] overrides per deployment
DEFAULT_MODEL_ALIASES: dict[str, str] = {
    "s5": "claude-sonnet-5",
    "s46": "claude-sonnet-4-6",
    "s45": "claude-sonnet-4-5",
    "c25": "composer-2.5",
    "c2": "composer-2",
    "op": "claude-opus-4-8",
    "op48": "claude-opus-4-8",
    "op46": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5",
    "auto": "default",
}


def resolve_model_input(name: str, aliases: dict[str, str]) -> str:
    """Map alias or slug to a model ID; unknown strings pass through unchanged."""
    key = name.strip().lower()
    return aliases.get(key, name.strip())

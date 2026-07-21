#!/usr/bin/env bash
# preToolUse hook (matcher: Write|Delete) — used only by readonly.hooks.json.
# permissions.json/auto_review and sandbox_options both explicitly exclude
# the native write/edit tool from their scope (see perms.py docstring); this
# hook is the mechanism that actually blocks it.
set -euo pipefail

cat <<'EOF'
{
  "permission": "deny",
  "user_message": "readonly mode: writes are blocked.",
  "agent_message": "This workspace is in readonly mode. Write/delete tool calls are blocked by a preToolUse hook. If a write is actually needed, tell the operator to run /perms standard first."
}
EOF

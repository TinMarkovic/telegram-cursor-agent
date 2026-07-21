---
name: ttd-feature
description: >
  Full pipeline. Pick the right starting phase based on what's provided, then
  execute forward without waiting. Covers research through documentation.
  Use for any scoped software change — feature, fix, or enhancement.
---

# Feature — Full Pipeline

Full SDLC: `llm/workflow/sdlc.md`  
Artifact catalog: `llm/workflow/llm-folder.md`  
Plan format: `llm/workflow/plans.md`

---

## Entry — pick the starting phase

**From a freeform prompt:**

| Signal | Start at |
|---|---|
| Small, clear, bounded | Phase 3 — `/ttd-plan` |
| Problem clear, solution needs scoping | Phase 1 — `/ttd-propose` |
| Ambiguous, risky, or large | Phase 0 — `/ttd-research` |

**From a ticket or input file:**  
Read the file. Extract: Summary, Packages, ACs, Dependencies.

| Ticket state | Start at |
|---|---|
| ACs clear + packages known | Phase 3 — `/ttd-plan` |
| ACs present, design unclear | Phase 1 — `/ttd-propose` |
| No ACs | Stop — infer from description and confirm before continuing |

When in doubt, ask one tight question to resolve the ambiguity. Don't over-research obvious things.

---

## Execution

1. Announce the starting phase and why
2. Complete the phase, produce the artifact
3. Announce what was produced and immediately move to the next phase
4. Stop only at gates (see below)

---

## Gates — always stop and surface

- Scope ambiguity that would change the phase output
- Low-confidence architectural or design choice
- No ACs or undeclared dependencies
- Plan todo requiring a human decision — mark `DECISION:` in content and stop
- Multiple valid approaches with non-trivial tradeoffs — present options, don't pick silently
- Verification steps cannot be drafted — requirement not understood, stop and clarify
- Verification file still has `TODO` placeholders when declaring implementation done

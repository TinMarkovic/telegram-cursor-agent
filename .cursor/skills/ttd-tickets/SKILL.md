---
name: ttd-tickets
description: >
  Phase 2 — Tickets. Break an approved proposal into assignable units of work.
  Each ticket has a summary, packages, relevant files, testing requirements,
  binary acceptance criteria, and declared dependencies.
---

# Tickets

Full phase spec: `llm/workflow/sdlc.md` — Phase 2  
Artifact format: `llm/workflow/llm-folder.md` — `tickets/*.md`

---

## Output

`llm/tickets/<feature>.md`

## Per ticket

- Summary (2–4 sentences: what it is, why it matters, what it changes)
- Packages — specific, not generic
- Relevant files with annotations (why each file matters)
- Testing requirements: unit + staging validation
- Acceptance criteria — binary, present or not
- `Depends on` — always declared, no implicit ordering

## Done when

All tickets have ACs and declared dependencies.

## Constraints

- ACs must be binary — no "should work" or "looks correct"
- `Depends on` is never implicit — if nothing, write `Depends on: none`
- Packages must be specific — not "backend" or "frontend"

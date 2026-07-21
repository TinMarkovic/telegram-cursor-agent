---
name: ttd-implement
description: >
  Phase 4 — Implementation. Execute the plan todos, produce code and a feature doc,
  and complete the verification file so it is walkable end-to-end.
---

# Implement

Full phase spec: `llm/workflow/sdlc.md` — Phase 4  
Artifact format: `llm/workflow/llm-folder.md` — `features/*.md` and `verify/*.md`

---

## Output

Code across the files listed in the plan  
`llm/features/<name>.md` — for any non-trivial change  
`llm/verify/<feature>.md` — completed (no TODOs remaining)

## Steps

1. Work through plan todos in order; update `status` as each completes
2. Feature doc: overview, key design decision, implementation by layer, edge cases, testing
3. Complete the verification file:
   - Fill all `TODO` placeholders with exact commands, queries, or UI steps
   - Add expected outputs — exact status codes, field values, UI states
   - Include at least one negative case per surface type
   - Confirm prerequisites are complete and findable

## Done when

All plan todos are `completed`, PR is ready, AND `llm/verify/<feature>.md` is fully populated and walkable.

## Hard stops — surface before proceeding

- Low-confidence architectural or design choice
- Significant change to project structure
- Destructive operations
- Multiple valid approaches with non-trivial tradeoffs — present options, don't pick silently
- Verification file still has `TODO` placeholders when declaring done

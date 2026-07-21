---
name: ttd-plan
description: >
  Phase 3 — Planning. Produce a .plan.md and a verification stub before any code is written.
  Use when tickets are ready or the task is clear enough to plan directly.
---

# Plan

Full phase spec: `llm/workflow/sdlc.md` — Phase 3  
Plan format: `llm/workflow/plans.md`  
Artifact format: `llm/workflow/llm-folder.md` — `plans/*.plan.md` and `verify/*.md`

---

## Output

`llm/plans/<feature>.plan.md` — YAML frontmatter todos + markdown body  
`llm/verify/<feature>.md` — verification stub (produced at the same time)

## Steps

1. Write all YAML frontmatter todos first — before any implementation detail
2. Body: files to create, files to modify, key patterns to follow
3. Cite the reference file for every pattern ("follows `create-invoice.ts`" not "follows existing patterns")
4. Mark the phase boundary — what is and isn't in scope
5. Produce the verification stub simultaneously:
   - Type: API / DB / UI / mixed
   - Prerequisites and test data needed
   - Step headers with what each step asserts
   - Fill in exact commands where known; `TODO` where not yet known

## Done when

Plan checklist passes (see `llm/workflow/plans.md`) AND verification stub exists.

## Constraints

- All todos in frontmatter before implementation starts
- If verification steps cannot be drafted, stop — the requirement isn't understood
- Multi-phase features get separate plan files per phase

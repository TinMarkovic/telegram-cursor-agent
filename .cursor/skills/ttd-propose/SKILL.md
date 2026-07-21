---
name: ttd-propose
description: >
  Phase 1 — Proposal. Define scope before writing tickets.
  Use when research is done and the problem needs a design + ROI case before
  breaking into tickets. Produces a scoping proposal with explicit V1/V2 split.
---

# Proposal

Full phase spec: `llm/workflow/sdlc.md` — Phase 1  
Artifact format: `llm/workflow/llm-folder.md` — `proposals/*.md`

---

## Output

`llm/proposals/<topic>.md`

## Steps

1. State the problem — ground it in Phase 0 research if it ran
2. Define V1 scope explicitly: what it delivers AND what it does not
3. Design: schema, runtime behavior, storage, future-proofing note
4. ROI: immediate / medium-term / architectural
5. List assumptions — if any are wrong, the proposal breaks
6. Tasks table with effort estimates (S = half day · M = 1–2 days · L = 3+ days)
7. Recommended sequencing
8. Deferred items table — every deferral needs a stated reason

## Done when

Scope agreed, V1/V2 split locked.

## Constraints

- Assumptions section is not optional
- Every deferred item needs an explicit reason
- V1/V2 split must be stated upfront — not buried

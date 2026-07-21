---
name: ttd-research
description: >
  Phase 0 — Research. Map the current system before committing to a solution.
  Use when a task is ambiguous, risky, or worth sizing. Produces a code reference
  map and named structural complexities. No recommendations.
---

# Research

Full phase spec: `llm/workflow/sdlc.md` — Phase 0  
Artifact format: `llm/workflow/llm-folder.md` — `analysis/*.md`

---

## Output

`llm/analysis/<topic>.md`

## Steps

1. Map the current system — relevant models, code paths, data flow
2. Build the code reference table (concern → file → what it does)
3. Name and number structural complexities explicitly
4. Close with observations — honest about what's hard and why

## Done when

Code reference map exists and all complexities are named.

## Constraints

- No recommendations here — that's Phase 1 (`/ttd-propose`)
- Every observation must be traceable to a file in the code reference table
- Separate confirmed / likely / unknown explicitly

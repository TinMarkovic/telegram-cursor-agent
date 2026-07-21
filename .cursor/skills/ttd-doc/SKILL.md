---
name: ttd-doc
description: >-
  Phase 5 — Write a PR description and implementation summary. Works through a
  structured questionnaire answerable from code, diff, tests, and production
  context. Saves output to llm/implementation-summary/; optionally produces a
  quick reference. Use when asked to write a PR description, implementation
  summary, or post-merge documentation.
---

# PR Description + Implementation Summary

**Phase 5** of the SDLC. Triggered after implementation is complete.  
Full phase spec: `llm/workflow/sdlc.md` — Phase 5

## Process

1. If there's no session context yet, run `git diff origin/main...HEAD` and `git log origin/main..HEAD --oneline` to establish scope. Skip if the work is already in context.
2. Work through each section's questions — answer from code, diff, tests, and prior conversation.
3. **When you can't answer a question from available context, ask.** Don't guess at manual verification steps, predecessor relationships, or production evidence.
4. Include only sections where the answers are meaningful. Omit sections with nothing to say.
5. **Manual verification is never optional.**
6. Save to `llm/implementation-summary/<feature>-<YYYY-MM-DD>.md`.

---

## Sections

### Summary
*Answer from: PR context, ticket, diff shape*

- Is this a fix, feature, or refactor?
- What problem does this solve, or what does this add?
- Was there a trigger — a bug report, a predecessor PR, a specific failing record?

One short paragraph or 2–3 bullets. No header needed if it leads the description.

---

### Context
*Include when this PR is part of a sequence. Answer from: git log, PR references, ticket.*

- Is there a predecessor or dependency PR? What did it do, and what did it leave incomplete?
- Where does this sit in the sequence? (first, follow-up, reverting a gate, final cleanup)
- What prior state must a reader understand to make sense of this change?

Skip if this PR is self-contained.

---

### Root cause
*Bug fixes only. Answer from: changed code, test that was encoding the bug, git blame.*

- What is the code path that produces the wrong output?
- Trace it: what value flows in → what condition is evaluated → what incorrect value comes out?
- What assumption was wrong or what case was unhandled?

Show the logic chain, not just the label. A line of math or pseudocode makes this section land.

---

### Evidence
*Include when a concrete case exists. Answer from: production records, test fixtures, error logs.*

- What is the specific record, payload, or request that reproduces the bug?
- State the observable values: key input fields, observed output, expected output.

One-liner or a small inline block. Skip if no concrete case is available.

---

### Changes
*Answer from: diff, changed files, sibling files for comparison.*

Write for the reviewer who needs to understand what happened, not audit every line. The goal is signal, not coverage.

- **Group by theme or layer** (schema → domain → lambda → frontend) rather than listing every file
- Lead each entry with the **decision or direction**, not a file inventory: "gate removed", "default starts at Not Invoiceable", "now unconditional", "cast at lambda boundary"
- **Collapse boilerplate** into one line: barrel exports, resolver registrations, codegen regeneration — one mention each, not individual bullets
- **Call out intentional non-changes** — files that were considered and left alone
- One entry per meaningful change. If five files moved in lockstep for the same reason, that's one bullet

---

### Tests
*Answer from: test files in the diff, test names.*

- What new test cases were added? Give them labels or names as they appear in code.
- What does each cover? (edge case, previously-wrong behavior, new execution path, negative case)
- Was any existing test encoding the bug? Name it and state what the corrected assertion is.

---

### Manual verification *(always include)*
*Answer from: your release/deploy process, production environment, monitoring tools, admin interfaces.*  
*If you don't know the right check, ask — don't fabricate steps.*

- Once deployed, how do you confirm this works?
- What is the concrete check: a specific record, a query, a log line, a UI state, a metric?
- What would the observable symptom be if this silently broke in production?

Write it so someone who didn't author the PR can execute it.

---

### Semantic side-effects
*Include when applicable. Answer from: version metadata files, migration scripts, downstream consumers.*

- Did a version constant change? What does bumping it trigger (re-processing, reclassification, cache invalidation)?
- Are there migration, backfill, or re-run implications?
- What should reviewers or on-call know before this merges?

---

### Appendix — LLM artifacts & post-mortem
*Always include if any artifacts exist. Answer from: `llm/` folder contents and session context.*

**Part 1 — Artifact index**

Scan `llm/` for artifacts related to this feature. These files exist locally and may not be in version control.

Check: `llm/plans/` · `llm/tickets/` · `llm/analysis/` · `llm/` root (proposals) · `llm/verify/`

Format:
> - `llm/plans/feature-name.plan.md` — phase 3 plan; all N todos completed
> - `llm/verify/feature-name.md` — verification steps; walked through / not yet run
> - `llm/tickets/feature.md` — ticket N this implements

**Part 2 — Plan vs. implementation post-mortem**

Read the plan file(s) and compare against what shipped. Document divergences — things that changed, were discovered mid-implementation, or weren't anticipated in the plan.

For each divergence:
- Name it (one bolded label)
- State what the plan said vs. what was implemented
- Explain why, if it matters

Also note: nothing removed from scope (if true), any known limitations that landed, and any patterns discovered that recur in this codebase.

If no plan existed, note what surprises or constraints emerged during implementation instead.

Omit the entire appendix only if no related artifacts exist and implementation had no divergences worth recording.

---

## Output format

Open the document with a **suggested commit message** block:

```
feat(scope): short imperative description

Body lines explain the why and what at the right altitude — not a file
inventory. Wrap at 100 characters. Two paragraphs max.
```

Follow with the PR description body. **Lead with the most important thing.** Bug fix → start with what was wrong. Feature → start with what it enables. Cleanup → start with what's gone and why.

**Changes entries** — group by theme, not file. Lead with the decision:
> Lambda boundary casts `ManualUploadStatus` to `'COMPLETED' | 'FAILED'` — `IN_PROGRESS` is not a valid completion state. Pattern will recur in any new lambda forwarding GraphQL enums to domain commands.

Put predecessor/related PR references at the bottom. Don't bury them in the summary.

---

## Additional outputs

**Implementation summary** — save the PR description to:
```
llm/implementation-summary/<feature>-<YYYY-MM-DD>.md
```
One page max. This is a record, not a tutorial.

**Quick reference** — produce `llm/quick-reference/<topic>.md` only if the feature introduces something that will be called or configured repeatedly. Code-first, no prose: primary operation → authorization → what happens → files → deploy/run.

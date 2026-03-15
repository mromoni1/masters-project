---
name: pr-workflow
description: Create pull requests and manage the PR workflow. Use when creating a PR, managing feature branch merges, or asking about PR conventions, code review process, or the collaborative feature branch workflow.
argument-hint: "PR or issue number"
allowed-tools:
  - Read
  - Grep
  - Glob
  - "Bash(gh pr *)"
  - "Bash(gh api *)"
  - "Bash(git *)"
---

# PR Workflow Skill

## Related Skills

- `github-issues` — PRs must reference an issue via `Closes #<number>`
- Branch naming rules: `.claude/rules/branch-naming.md`

## Before Creating a PR

1. **Verify branch naming** — must match `<type>/issue-<number>-<short-description>`
2. **Check diff size** — warn if over ~400 changed lines and suggest splitting
3. **Ensure commits reference the issue** — e.g., `Add validation (#12)`
4. **Push the branch** to remote if not already pushed

## Creating a PR

Use the PR template (`.github/PULL_REQUEST_TEMPLATE.md`):

```bash
gh pr create \
  --title "Short descriptive title" \
  --body "## Summary

Closes #<issue-number>

## Changes

- Change 1
- Change 2

## How to Test

1. Step 1
2. Step 2

## Checklist

- [x] PR is under ~400 changed lines
- [x] Branch follows naming convention
- [x] Commits reference the issue number
- [ ] Tests pass

```

## Key Rules

- Always include `Closes #<number>` or `Fixes #<number>` in the PR body
- Target the `master` branch (or parent feature branch for sub-branches)
- Use **merge commits only** — never squash or rebase
- Delete the branch after merging

See [reference.md](reference.md) for the git commands.

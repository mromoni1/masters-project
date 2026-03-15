---
name: github-issues
description: Create and manage GitHub issues following project conventions. Use when creating issues, managing issue labels, assigning issues, setting up milestones, or asking about issue conventions and requirements.
argument-hint: "issue title or number"
allowed-tools:
  - Read
  - Grep
  - Glob
  - "Bash(gh issue *)"
  - "Bash(gh api *)"
  - "Bash(gh label *)"
---

# GitHub Issues Skill

## Related Skills

- `pr-workflow` — PRs reference issues via `Closes #<number>`

## Creating Issues

Every issue must have:

1. **Descriptive title** — clear and concise
2. **Description** — what needs to be done and why
3. **Acceptance criteria** — checklist of testable criteria
4. **Label** — exactly one of: `feature`, `task`, or `bug`

## Labels

The project uses these labels:

- `feature` — new functionality
- `task` — development work that isn't a feature or bug
- `bug` — something that's broken

If labels don't exist yet, create them:

```bash
gh label create feature --description "New functionality" --color 0E8A16
gh label create task --description "Development task" --color 1D76DB
gh label create bug --description "Something is broken" --color D93F0B
```

## Creating Issues via CLI

Read the matching template in `.github/ISSUE_TEMPLATE/` (feature.yml, task.yml, or bug.yml) and use its structure for the `--body`. Example:

```bash
gh issue create \
  --title "Add search-by-title to items list endpoint" \
  --label "feature" \
  --body "## Description
Add a query parameter to the items endpoint that filters by title.

## Acceptance Criteria
- [ ] Search is case-insensitive
- [ ] Empty query returns all items
- [ ] Tests added for all cases"
```

For task and bug issues, follow the same pattern using the corresponding template structure.

## Rules

- Use the GitHub issue templates (feature, task, or bug) when creating from the UI

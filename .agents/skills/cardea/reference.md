# Cardea Reference

## Safety Matrix

### `create-safe`
- creating a brand new project when the target path does not exist
- creating a new branch, tag, file, or setting only when that exact target is absent
- opening a merge request for a newly created branch

### `review-required`
- changing any existing file path in an existing repository
- replacing template content that already exists in the target repo
- updating project settings, variables, hooks, protections, labels, or members
- pushing commits that alter existing remote content

### `explicit-approval-only`
- force pushes
- mirror pushes
- deleting projects, branches, tags, files, or settings
- rewriting history

## Default Publish Strategy
1. Inspect remote state first.
2. Execute only `create-safe` actions immediately.
3. For `review-required` actions, prepare a diff or before/after snapshot.
4. Wait for approval.
5. Publish the exact reviewed change set.
6. Verify links, branches, files, and settings afterward.

## Utility Script Quick Start
- Check auth and API reachability:
  `python .agents/skills/cardea/scripts/gitlab_ops.py auth-status --check-api`
- Confirm whether a new project path is safe to create:
  `python .agents/skills/cardea/scripts/gitlab_ops.py project-check group/new-repo`
- Confirm whether a branch name is safe to create:
  `python .agents/skills/cardea/scripts/gitlab_ops.py branch-check group/repo feature/new-branch`
- Confirm whether a repository file already exists at a ref:
  `python .agents/skills/cardea/scripts/gitlab_ops.py file-check group/repo path/to/file --ref main`
- Prepare but do not create a project yet:
  `python .agents/skills/cardea/scripts/gitlab_ops.py create-project group/new-repo --dry-run`
- Compare two local trees and write a review package:
  `python .agents/scripts/overlay_guard.py plan source-dir target-dir --manifest overlay.json --review overlay.md`
- Copy only missing files from one tree into another:
  `python .agents/scripts/overlay_guard.py copy-missing source-dir target-dir`

## Cross-Project Assembly Pattern
For a workflow like "analyze `A`, `B`, and `C`; create a new project from `C`; import config from `B`":

1. Analyze `A`, `B`, and `C` read-only.
2. Build an import matrix:
   - what comes from `C`
   - what comes from `B`
   - what is informational from `A`
3. Check whether the new project path exists.
4. If absent, create the new project and seed it from `C`.
5. Copy only missing config from `B` directly.
6. For any path or setting already present in the target, stop and prepare a review package.
7. After approval, publish only the reviewed replacements.

## Review Package Checklist
- target project and namespace
- existing objects that would be changed
- exact file diffs or before/after settings
- commands or API calls that will run after approval
- rollback or containment note when applicable

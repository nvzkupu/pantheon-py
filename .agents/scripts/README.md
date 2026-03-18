# Shared Utility Scripts

Shared utilities live in `.agents/scripts/` when they support multiple members of
the Pantheon or enforce repo-wide operational rules. Agent-local utilities live
under `.agents/skills/<agent>/scripts/` when they are tightly coupled to one
member's workflow.

## Placement Rules

- Use `.agents/scripts/` for shared validation, safety gates, repo inspection, or
  workflow helpers that more than one agent can invoke.
- Use `.agents/skills/<agent>/scripts/` for domain-specific helpers that embody a
  single member's methodology or external-system contract.
- Prefer stdlib-first implementations. If a script needs a third-party package,
  it must rely on an existing project dependency or document the requirement
  explicitly.

## Required Conventions

- Every script must expose `--help` and a stable CLI with explicit exit codes.
- Scripts that emit structured results should support `--json`.
- Scripts must never print secrets or tokens.
- Shared scripts must be listed in this file.
- Agent-local scripts must be documented in the owning skill's `SKILL.md` or
  `reference.md`.
- Every new script must have tests under `tests/`.

## Shared Script Index

- `doctor.py`: Diagnose Pantheon workspace health, import resolution, env
  readiness, and optional gateway/GitLab/skillgrade requirements.
- `overlay_guard.py`: Compare two local trees, classify paths as
  `create-safe` or `review-required`, generate a review package, and optionally
  copy only missing files.
- `secret_scan.py`: Scan a file tree for likely secrets and dangerous
  `eval`/`exec` usage with redacted previews and CI-friendly exit codes.
- `skill_validate.py`: Validate Pantheon operational consistency across skill
  rosters, eval coverage, shared script docs, agent-local script docs, and
  Cursor command discoverability.

## Agent-Local Examples

- `cardea/scripts/gitlab_ops.py`: Safe GitLab project, branch, file, and
  creation checks for Cardea's approval-gated remote workflows.

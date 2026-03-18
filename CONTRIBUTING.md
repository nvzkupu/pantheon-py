# Contributing to Pantheon

## Setup

```bash
git clone <repo-url>
cd pantheon-py
pip install -e ".[dev]"
```

## Development Loop

```bash
make check    # runs lint + tests
make test     # tests only
make lint     # lint only
make validate-skills
```

## Code Style

- Python 3.10+, type hints everywhere
- Ruff for linting (config in `pyproject.toml`)
- No unnecessary comments — code should be self-documenting
- Docstrings on modules and public classes/functions

## Tests

- pytest with class-based organization
- Use `unittest.mock` for external dependencies (HTTP, filesystem)
- Name pattern: `test_<module>.py` with `Test<Class>` groups
- Run `make test` before pushing
- Run `make validate-skills` when changing skills, rosters, evals, or utility scripts

## Adding a New Agent Skill

1. Create `.agents/skills/<name>/SKILL.md`
2. Include YAML frontmatter with `name`, `description`, and `metadata`
3. The markdown body becomes the agent's system prompt
4. Add the agent to the roster in `README.md`, `AGENTS.md`, and `.cursor/rules/pantheon.mdc`
5. Add `evals/<name>/eval.yaml` plus fixtures/graders as needed
6. Run `make validate-skills`

## Adding a Utility Script

1. Use `.agents/scripts/` for shared helpers and `.agents/skills/<agent>/scripts/` for agent-local helpers
2. Keep CLIs stable, explicit, and safe by default; support `--json` when structured output is useful
3. Document shared scripts in `.agents/scripts/README.md`
4. Document agent-local scripts in the owning skill's `SKILL.md` or `reference.md`
5. Add tests under `tests/`
6. Run `make validate-skills` and `make test`

## Adding a New Tool

1. Subclass `Tool` in `src/pantheon/tools.py` (or a new module)
2. Implement `name()`, `description()`, `parameters()`, `execute()`
3. Use `strict_schema()` for parameters to enforce strict mode
4. Register in `builtins()` if it should be available by default
5. Add tests

## Pull Requests

- One logical change per PR
- Tests must pass (`make check`)
- Update README if adding user-facing features

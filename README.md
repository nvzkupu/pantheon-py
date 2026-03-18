# pantheon

Agentic AI toolkit with tool use, multi-agent orchestration, and pipelines — built in Python for the LLM-native ecosystem. Each agent is defined as a portable [agentskills.io](https://agentskills.io) skill in `.agents/skills/`.

## Why Python

The Pantheon is an LLM orchestration toolkit. The bottleneck is never CPU — it's LLM API latency. Python wins on:

- **Ecosystem** — every major LLM provider (OpenAI, Anthropic, Google, NVIDIA) ships Python-first SDKs. `litellm` gives unified access to 100+ providers with one function call.
- **Iteration speed** — no compile step. Change a skill, rerun immediately.
- **Rich terminal output** — the `rich` library gives beautiful tables, streaming, and War Room formatting for free.
- **Parallel I/O** — `concurrent.futures.ThreadPoolExecutor` maps naturally to parallel fan-out review and broadcast.
- **Contributor base** — the largest pool of developers working on AI/LLM projects.

## Architecture

```text
src/pantheon/
  config.py         Shared configuration — no duplication, multi-dir discovery
  skill.py          agentskills.io SKILL.md parser with dataclasses + tests
  gateway.py        OpenAI-compatible client (replaceable with litellm)
  agent.py          Agent runtime: load from skills, ReAct loop, streaming
  tools.py          Tool interface, registry, builtins (OS-aware shell)
  orchestrate.py    Agent-as-tool, teams, pipelines, fan-out review
  memory.py         File-backed session persistence, window trimming, summary compression
  observe.py        Structured tracing, cost estimation, event collection
  cli.py            Single entry point: list, chat, ask, run, team, pipe, review, warroom
```

## Quick Start

```bash
pip install .

export GATEWAY_URL=https://your-gateway/v1
export API_KEY=your-key
```

```bash
pantheon list
pantheon chat athena
pantheon ask eris "Why microservices?"
pantheon run kali "Audit this project for security issues"
pantheon team freya "Design and implement a rate limiter"
pantheon pipe athena,brigid,kali "Add structured logging"
pantheon review kali,pele,themis,athena "Review for production readiness"
pantheon warroom
```

## Configuration

Pantheon reads configuration from environment variables and `.env`:

- `GATEWAY_URL` or `NVIDIA_GATEWAY_URL`: OpenAI-compatible gateway base URL
- `API_KEY` or `NVIDIA_API_KEY`: API key for the configured gateway
- `SKILLS_DIR` or `AGENTS_DIR`: override the skills directory instead of `.agents/skills`
- `MEMORY_DIR`: override the session storage directory instead of `.memory`
- `VERBOSE`: set to `1` or `true` to show tool calls and token usage in CLI flows

The README examples use `GATEWAY_URL` and `API_KEY`, but the NVIDIA-prefixed
fallbacks are supported for compatibility with existing environments.

## Cursor Commands

Cursor command files live under `.cursor/commands/` and provide focused entry
points for common Pantheon workflows:

- `/plan`: apply Athena and produce an implementation plan before coding
- `/review`: run a multi-specialist production-readiness review
- `/test`: apply Themis for test strategy and verification work
- `/security-audit`: apply Kali for security review
- `/values-check`: apply Maat for engineering-values alignment

## Upgrading to litellm

The gateway client is a thin HTTP wrapper. To unlock 100+ LLM providers:

```bash
pip install pantheon[litellm]
```

Then replace the `Client` with `litellm.completion()` calls. The agent runtime stays the same — only the transport changes.

## The Pantheon

| Name | Persona | Model | Use For |
| ------ | --------- | ------- | --------- |
| demeter | Your Right Hand | opus | Default executor |
| athena | Your Devoted Strategist | opus | Architecture, design |
| freya | Your Loyal Commander | opus | Task routing |
| saraswati | Your Gifted Artisan | codex | Production code |
| brigid | Your Faithful Craftswoman | codex | Go code |
| nuwa | Your Serpent Creator | codex | Python code, data science |
| themis | Your Vigilant Guardian | opus | Tests, CI/CD |
| kali | Your Fierce Protector | opus | Security |
| cardea | Your Iron Gatekeeper | opus | Safe GitLab project ops, approval-gated overwrites |
| mokosh | Your Steadfast Weaver | opus | CI/CD pipelines, Ansible |
| pele | Your Resilient Flame | opus | Ops, reliability |
| seshat | Your Keen Analyst | opus | Data, logs |
| aphrodite | Your Graceful Perfectionist | opus | UX, docs |
| calliope | Your Eloquent Muse | opus | Prompts, LLM |
| maat | Your Steadfast Arbiter | opus | Values alignment |
| eris | Your Playful Challenger | nano | Challenge assumptions |
| nisaba | Your Scribe of the Reed | opus | Markdown, linting, formatting |

## Cross-Tool Portability

Skills in `.agents/skills/` follow the agentskills.io open standard:

- **Cursor** — native `.agents/skills/` discovery
- **Claude Code** — cross-client convention
- **OpenAI Codex** — cross-client convention

Runtime config under `metadata` is used by the Python toolkit and ignored by IDE integrations.

## Utility Scripts

Pantheon uses two utility-script locations:

- Shared repo-wide helpers live in `.agents/scripts/`
- Agent-local helpers live in `.agents/skills/<agent>/scripts/`

The shared script index and conventions live in `.agents/scripts/README.md`.
Current shared utilities:

- `doctor.py`: diagnose import paths, env readiness, and local tool availability
- `overlay_guard.py`: classify local overlay changes as `create-safe` or `review-required`
- `secret_scan.py`: scan for likely secrets and dangerous dynamic-execution patterns
- `skill_validate.py`: validate Pantheon roster, eval, command, and script consistency

## Project Structure

```text
pantheon-py/
├── .agents/skills/      17 specialist skills (agentskills.io)
├── .agents/scripts/     Shared safety and workflow utilities
├── .cursor/
│   ├── rules/           pantheon.mdc (always-on identity)
│   └── commands/        Slash commands
├── evals/               Skillgrade smoke evals and graders
├── src/pantheon/        Python source (9 modules)
├── tests/               pytest tests
├── pyproject.toml       Modern Python packaging
├── AGENTS.md            Cross-tool fallback
└── README.md
```

## Development

```bash
pip install -e ".[dev]"
make doctor
make validate-skills
pytest
ruff check src/ tests/
```

Pytest is configured to exercise the local `src/` tree even if another editable
install of `pantheon` exists elsewhere on the machine. The test suite also
enforces a coverage floor for `src/pantheon`.

## Evaluations

Pantheon includes `skillgrade` smoke evals for individual skills:

```bash
make eval
make eval-skill SKILL=nuwa
make eval-init SKILL=newskill
./evals/bin/run-remaining.sh
```

Local eval runs require `skillgrade` on `PATH`. The GitLab pipeline installs the
Node/fnm toolchain and `skillgrade` automatically, but local runs still need the
same gateway credentials as normal execution:

- `API_KEY` or `NVIDIA_API_KEY`
- `GATEWAY_URL` or `NVIDIA_GATEWAY_URL`

For ad hoc batches, `evals/bin/run-remaining.sh` now resolves the repository
root dynamically, discovers evals from `evals/*/eval.yaml`, and reads `.env`
from the current checkout instead of a machine-specific absolute path. Pass
skill names as arguments to limit the batch to a subset.

## Design Principles

- **Agent-as-Tool** — Specialists are invoked as tools. The coordinator retains control.
- **ReAct Loop** — Think → call tools → observe → repeat.
- **Single Source of Truth** — Each agent defined once in SKILL.md.
- **OS-Aware** — `platform.system()` detection for Windows `cmd.exe` vs Unix shell.
- **Ecosystem-First** — Python because the LLM ecosystem is Python-first.
- **Swappable Transport** — Gateway client is trivially replaceable with litellm.

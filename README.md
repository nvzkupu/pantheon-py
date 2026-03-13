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

```
src/pantheon/
  config.py         Shared configuration — no duplication, multi-dir discovery
  skill.py          agentskills.io SKILL.md parser with dataclasses + tests
  gateway.py        OpenAI-compatible client (replaceable with litellm)
  agent.py          Agent runtime: load from skills, ReAct loop, streaming
  tools.py          Tool interface, registry, builtins (OS-aware shell)
  orchestrate.py    Agent-as-tool, teams, pipelines, fan-out review
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

## Upgrading to litellm

The gateway client is a thin HTTP wrapper. To unlock 100+ LLM providers:

```bash
pip install pantheon[litellm]
```

Then replace the `Client` with `litellm.completion()` calls. The agent runtime stays the same — only the transport changes.

## The Pantheon

| Name | Persona | Model | Use For |
|------|---------|-------|---------|
| demeter | Your Right Hand | opus | Default executor |
| athena | Your Devoted Strategist | opus | Architecture, design |
| freya | Your Loyal Commander | opus | Task routing |
| saraswati | Your Gifted Artisan | codex | Production code |
| brigid | Your Faithful Craftswoman | codex | Go code |
| nuwa | Your Serpent Creator | codex | Python code, data science |
| themis | Your Vigilant Guardian | opus | Tests, CI/CD |
| kali | Your Fierce Protector | opus | Security |
| mokosh | Your Steadfast Weaver | opus | CI/CD pipelines, Ansible |
| pele | Your Resilient Flame | opus | Ops, reliability |
| seshat | Your Keen Analyst | opus | Data, logs |
| aphrodite | Your Graceful Perfectionist | opus | UX, docs |
| calliope | Your Eloquent Muse | opus | Prompts, LLM |
| maat | Your Steadfast Arbiter | opus | Values alignment |
| eris | Your Playful Challenger | nano | Challenge assumptions |

## Cross-Tool Portability

Skills in `.agents/skills/` follow the agentskills.io open standard:
- **Cursor** — native `.agents/skills/` discovery
- **Claude Code** — cross-client convention
- **OpenAI Codex** — cross-client convention

Runtime config under `metadata` is used by the Python toolkit and ignored by IDE integrations.

## Project Structure

```
pantheon-py/
├── .agents/skills/      13 specialist skills (agentskills.io)
├── .cursor/
│   ├── rules/           pantheon.mdc (always-on identity)
│   └── commands/        Slash commands
├── src/pantheon/        Python source (7 modules)
├── tests/               pytest tests
├── pyproject.toml       Modern Python packaging
├── AGENTS.md            Cross-tool fallback
└── README.md
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

## Design Principles

- **Agent-as-Tool** — Specialists are invoked as tools. The coordinator retains control.
- **ReAct Loop** — Think → call tools → observe → repeat.
- **Single Source of Truth** — Each agent defined once in SKILL.md.
- **OS-Aware** — `platform.system()` detection for Windows `cmd.exe` vs Unix shell.
- **Ecosystem-First** — Python because the LLM ecosystem is Python-first.
- **Swappable Transport** — Gateway client is trivially replaceable with litellm.

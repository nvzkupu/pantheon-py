# Changelog

## 0.1.0 — Initial Release

### Added
- Agent runtime with ReAct loop, streaming, and tool dispatch
- OpenAI-compatible gateway client with retry logic and SSE streaming
- Tool interface with Registry, strict schema validation, and built-in tools (shell, read, write, list, search)
- Multi-agent orchestration: Team (agent-as-tool), Pipeline (sequential), Review (fan-out + synthesize)
- SKILL.md parser following agentskills.io specification
- File-backed session persistence with window trimming and summary compression
- Structured tracing and cost estimation
- CLI with commands: list, chat, ask, run, team, pipe, review, warroom
- 16 specialist agent skills
- Optional path restrictions on file tools for sandboxed execution
- GitHub Actions CI pipeline (pytest + ruff, Python 3.10/3.11/3.12)

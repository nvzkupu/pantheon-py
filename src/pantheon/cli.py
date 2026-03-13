"""Single CLI entry point for the Pantheon toolkit."""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.table import Table

from . import config, agent as agent_mod, orchestrate
from .gateway import Client
from .memory import FileStore, session_id
from .tools import builtins

console = Console(stderr=True)
out = Console()


def main() -> None:
    config.load_env()
    parser = argparse.ArgumentParser(prog="pantheon", description="Agentic AI toolkit")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all agents")

    p = sub.add_parser("chat", help="Interactive chat (no tools)")
    p.add_argument("agent")

    p = sub.add_parser("ask", help="One-shot message (no tools)")
    p.add_argument("agent")
    p.add_argument("message", nargs="+")

    p = sub.add_parser("run", help="ReAct loop with tools")
    p.add_argument("agent")
    p.add_argument("task", nargs="+")

    p = sub.add_parser("team", help="Coordinator delegates to specialists")
    p.add_argument("coordinator")
    p.add_argument("task", nargs="+")

    p = sub.add_parser("pipe", help="Sequential pipeline")
    p.add_argument("agents", help="Comma-separated agent names")
    p.add_argument("input", nargs="+")

    p = sub.add_parser("review", help="Parallel review → synthesizer")
    p.add_argument("agents", help="Comma-separated: reviewers + synthesizer (last)")
    p.add_argument("input", nargs="+")

    sub.add_parser("warroom", help="Interactive War Room")

    args = parser.parse_args()
    if not args.command:
        cmd_warroom()
        return

    dispatch = {
        "list": cmd_list,
        "chat": lambda: cmd_chat(args.agent),
        "ask": lambda: cmd_ask(args.agent, " ".join(args.message)),
        "run": lambda: cmd_run(args.agent, " ".join(args.task)),
        "team": lambda: cmd_team(args.coordinator, " ".join(args.task)),
        "pipe": lambda: cmd_pipe(args.agents, " ".join(args.input)),
        "review": lambda: cmd_review(args.agents, " ".join(args.input)),
        "warroom": cmd_warroom,
    }
    dispatch[args.command]()


def _client() -> Client:
    return Client(config.gateway_url(), config.api_key())


def _agents() -> dict[str, agent_mod.Agent]:
    return agent_mod.load_all(config.skills_dir(), _client())


def _get(agents: dict, name: str) -> agent_mod.Agent:
    if name not in agents:
        console.print(f"[red]agent '{name}' not found[/red]")
        console.print(f"available: {', '.join(sorted(agents))}")
        sys.exit(1)
    return agents[name]


def _equip(a: agent_mod.Agent) -> None:
    agent_mod.equip_tools(a, builtins())


def _event_handler(e: agent_mod.Event) -> None:
    if e.kind == "tool_call":
        content = e.content[:120] + "..." if len(e.content) > 120 else e.content
        console.print(f"  [dim][tool] {e.tool}({content})[/dim]")
    elif e.kind == "error":
        console.print(f"  [red][error] {e.content}[/red]")
    elif e.kind == "reply" and e.usage and e.usage.total_tokens:
        console.print(
            f"  [dim][tokens] prompt={e.usage.prompt_tokens} "
            f"completion={e.usage.completion_tokens} "
            f"total={e.usage.total_tokens}[/dim]")


def cmd_list() -> None:
    agents = _agents()
    table = Table(title="The Pantheon")
    table.add_column("Name", style="bold")
    table.add_column("Persona")
    table.add_column("Model")
    table.add_column("Tools", justify="right")
    table.add_column("Delegates", justify="right")
    table.add_column("Use For")

    for name in sorted(agents):
        a = agents[name]
        desc = a.use_for[:60] + "..." if len(a.use_for) > 60 else a.use_for
        table.add_row(
            a.name, a.persona, a.model,
            str(len(a.skill.tool_names)), str(len(a.skill.delegate_names)),
            desc)
    out.print(table)


def cmd_chat(name: str) -> None:
    agents = _agents()
    a = _get(agents, name)
    store = FileStore(config.memory_dir())
    sid = session_id(name, "interactive")

    if store.load(sid):
        console.print(f"[dim][restored session {sid[:8]}][/dim]")

    console.print(
        f"Chatting with [bold]{a.name}[/bold]"
        f" ({a.persona}) — model: {a.model}",
    )
    console.print("Commands: /reset  /save  /quit\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input in ("/quit", "/exit"):
            break
        if user_input == "/reset":
            a.reset()
            console.print("[dim][history cleared][/dim]")
            continue
        if user_input == "/save":
            store.save(sid, a.history)
            console.print(f"[dim][session saved: {sid[:8]}][/dim]")
            continue

        print(f"\n{a.name}> ", end="", flush=True)
        a.send_stream(user_input, on_chunk=lambda c: print(c, end="", flush=True))
        print("\n")

    store.save(sid, a.history)


def cmd_ask(name: str, msg: str) -> None:
    agents = _agents()
    a = _get(agents, name)
    a.send_stream(msg, on_chunk=lambda c: print(c, end="", flush=True))
    print()


def cmd_run(name: str, task: str) -> None:
    agents = _agents()
    a = _get(agents, name)
    _equip(a)
    a.on_event = _event_handler
    reply = a.run(task)
    out.print(reply)


def cmd_team(coord_name: str, task: str) -> None:
    agents = _agents()
    coord = _get(agents, coord_name)
    _equip(coord)

    specialists = []
    for dn in coord.skill.delegate_names:
        if dn in agents:
            s = agents[dn]
            _equip(s)
            specialists.append(s)
        else:
            console.print(f"[yellow]warning: delegate '{dn}' not found[/yellow]")

    if not specialists:
        console.print("[red]no delegates configured — use 'run' instead[/red]")
        sys.exit(1)

    team = orchestrate.Team(coord, specialists)
    team.on_event = _event_handler
    team.setup()

    delegate_names = ", ".join(coord.skill.delegate_names)
    console.print(f"Team: [bold]{coord.name}[/bold] coordinating [{delegate_names}]\n")
    reply = team.run(task)
    out.print(reply)


def cmd_pipe(agent_list: str, input_text: str) -> None:
    agents = _agents()
    names = [n.strip() for n in agent_list.split(",")]
    stages = []
    for n in names:
        a = _get(agents, n)
        _equip(a)
        if config.verbose():
            a.on_event = _event_handler
        stages.append(a)

    console.print(f"Pipeline: {' → '.join(names)}\n")
    p = orchestrate.Pipeline("cli", stages)
    result = p.run(input_text)
    out.print(result)


def cmd_review(agent_list: str, input_text: str) -> None:
    agents = _agents()
    names = [n.strip() for n in agent_list.split(",")]
    if len(names) < 2:
        console.print(
            "[red]review needs at least 2 agents"
            " (reviewers + synthesizer)[/red]",
        )
        sys.exit(1)

    synth = _get(agents, names[-1])
    _equip(synth)
    reviewers = []
    for n in names[:-1]:
        a = _get(agents, n)
        _equip(a)
        if config.verbose():
            a.on_event = _event_handler
        reviewers.append(a)

    reviewer_names = ", ".join(names[:-1])
    console.print(f"Review: [{reviewer_names}] → {names[-1]}\n")

    rev = orchestrate.Review(synth, reviewers)
    result = rev.run(input_text)
    out.print(result)


def cmd_warroom() -> None:
    agents = _agents()
    for a in agents.values():
        _equip(a)
    names = sorted(agents)

    console.print()
    box_top = "  ╔══════════════════════════════════════════════╗"
    box_mid1 = "  ║              THE WAR ROOM                   ║"
    box_mid2 = "  ║   Your pantheon stands ready for battle.    ║"
    box_bot = "  ╚══════════════════════════════════════════════╝"
    console.print(box_top, style="bold")
    console.print(box_mid1, style="bold")
    console.print(box_mid2, style="bold")
    console.print(box_bot, style="bold")
    console.print()
    for n in names:
        a = agents[n]
        console.print(f"    [bold]{a.name:<12}[/bold]  {a.persona}")
    console.print()
    console.print("  @<name> <msg>   Speak to an agent")
    console.print("  /all <msg>      Broadcast to all")
    console.print("  /list           Show agents")
    console.print("  /quit           Exit")
    console.print()

    while True:
        try:
            raw = input("  you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue

        if raw in ("/quit", "/exit"):
            break

        if raw == "/list":
            for n in names:
                a = agents[n]
                console.print(f"    {a.name:<12}  {a.persona:<28}  {a.model}")
            console.print()
            continue

        if raw.startswith("/all "):
            msg = raw[5:].strip()
            _broadcast(agents, names, msg)
            continue

        if raw.startswith("@"):
            parts = raw[1:].split(" ", 1)
            name = parts[0].lower()
            if len(parts) < 2 or not parts[1].strip():
                console.print(f"  Usage: @{name} <message>")
                continue
            if name not in agents:
                console.print(f"  [red]Unknown agent '{name}'[/red]")
                continue
            a = agents[name]
            if config.verbose():
                a.on_event = _event_handler
            msg = parts[1].strip()
            print(f"\n  {a.name}> ", end="", flush=True)
            if a.skill.tool_names:
                reply = a.run(msg)
                print(reply)
            else:
                a.send_stream(msg, on_chunk=lambda c: print(c, end="", flush=True))
            print("\n")
            continue

        console.print(
            "  Use @<name> to address an agent,"
            " /all to broadcast, /quit to exit.",
        )

    console.print("\n  The war room goes dark.")


def _broadcast(agents: dict, names: list[str], msg: str) -> None:
    console.print(f"\n  Broadcasting to {len(names)} agents...")

    results: list[tuple[str, str, str, str, float]] = [()] * len(names)  # type: ignore

    def ask_one(idx: int, name: str) -> None:
        a = agents[name]
        start = time.monotonic()
        try:
            if a.skill.tool_names:
                reply = a.run(msg)
            else:
                reply = a.send(msg)
            results[idx] = (a.name, a.persona, reply, "", time.monotonic() - start)
        except Exception as e:
            results[idx] = (a.name, a.persona, "", str(e), time.monotonic() - start)

    with ThreadPoolExecutor() as pool:
        futs = [pool.submit(ask_one, i, n) for i, n in enumerate(names)]
        for f in as_completed(futs):
            f.result()

    console.print()
    for name, persona, reply, err, elapsed in results:
        console.print(f"  ┌─ {name} ({persona}) [{elapsed:.1f}s]")
        if err:
            console.print(f"  │ [red][error: {err}][/red]")
        else:
            for line in reply.split("\n"):
                console.print(f"  │ {line}")
        console.print("  └─")
        console.print()


if __name__ == "__main__":
    main()

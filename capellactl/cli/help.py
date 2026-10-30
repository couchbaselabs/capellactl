"""help, help topics, help config and shell completion (CAP-034). Works offline, without an API key."""

from __future__ import annotations

import difflib
import re
from importlib import resources
from typing import Any

import click
from click.shell_completion import get_completion_class

from capellactl.cli.console import out, stdout_is_tty
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.config.loader import load_schema

TOPICS: dict[str, str] = {
    "getting-started": "configure → init or sync → validate → plan → apply",
    "config": "capella.yaml layout, secret references, defaults, .yaml/.yml discovery",
    "idempotency": "plan symbols, how resources are matched, what is compared",
    "scaling": "scale out, in and up; limits; scale-in checks; --step",
    "hibernation": "power off/on, weekly on/off schedule, pause/resume",
    "backup": "cluster backups and bucket backups: schedules, back up now, restore, export",
    "credentials": "database credentials, generated passwords, rotation",
    "safety": "deletion protection, prune, cascade, confirmations",
    "exit-codes": "what each exit code means",
    "ci": "pipelines: --auto-approve, --quiet, gating on plan, GitHub Actions and GitLab examples",
    "environment": "API key, organization, profiles, environment variables, precedence",
}

GETTING_STARTED = """\
Getting started:
  1. capellactl configure         save your API Key Token (OS keychain) and organization
  2. capellactl init              describe a new environment (or: capellactl sync --project NAME)
  3. capellactl validate          check capella.yaml offline
  4. capellactl plan              see what would change
  5. capellactl apply             make Capella match the file (run it again: "No changes")
"""

MUTABILITY = {
    "updatable": "updatable in place",
    "immutable": "immutable after creation (changing it is BLOCKED; requires a new resource)",
    "key": "identifies the resource (natural key)",
    "replace": "changing it re-creates the entry (the API has no update)",
    "rotate-only": "set on create; changed only with --rotate-password",
    "tool": "capellactl setting (not sent to Capella)",
}


# --------------------------------------------------------------- topic pages
def topic_text(name: str) -> str:
    return resources.files("capellactl.help").joinpath(f"{name}.md").read_text(encoding="utf-8")


def render_markdown(text: str) -> None:
    if stdout_is_tty():
        from rich.console import Console
        from rich.markdown import Markdown

        Console().print(Markdown(text))
    else:
        out(text.rstrip("\n"))


# ------------------------------------------------------------ schema fields
def _resolve(node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if not ref:
        return node
    target: Any = load_schema()
    for part in ref.lstrip("#/").split("/"):
        target = target[part]
    return {**target, **{k: v for k, v in node.items() if k != "$ref"}}


LEGACY_ROOT_KEYS = {"project", "clusters"}  # single-project form; documented through projects.*


def _walk_schema(node: dict[str, Any], path: str, acc: dict[str, dict[str, Any]]) -> None:
    node = _resolve(node)
    if isinstance(node.get("items"), dict):
        node = {**node, "items": _resolve(node["items"])}
    props = node.get("properties")
    if node.get("type") == "object" and props:
        if path and path not in acc:  # keep the enclosing array node for list fields
            acc[path] = node
        for k, v in props.items():
            if not path and k in LEGACY_ROOT_KEYS:
                continue
            _walk_schema(v, f"{path}.{k}" if path else k, acc)
        return
    if node.get("type") == "array" and isinstance(node.get("items"), dict) and node["items"].get("type") == "object":
        acc[path] = node
        _walk_schema(node["items"], path, acc)
        return
    acc[path] = node


def schema_fields() -> dict[str, dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}
    _walk_schema(load_schema(), "", acc)
    return acc


def leaf_fields() -> dict[str, dict[str, Any]]:
    return {k: v for k, v in schema_fields().items() if "x-mutability" in v or not (
        v.get("type") == "object" or (v.get("type") == "array" and isinstance(v.get("items"), dict)
                                      and v["items"].get("type") == "object"))}


def normalize_field_path(p: str) -> str:
    """Drop list indexes; map the single-project form (clusters.…, project.…) to projects.…"""
    p = re.sub(r"\[\d*\]", "", p).strip(".")
    if p == "clusters" or p.startswith("clusters."):
        return "projects." + p
    if p == "project":
        return "projects"
    if p.startswith("project."):
        return "projects." + p[len("project."):]
    return p


def field_detail(path: str, node: dict[str, Any]) -> str:
    lines = [path, "", f"  {node.get('description', '')}", ""]
    t = node.get("type")
    if not t and node.get("oneOf"):
        t = " | ".join(sorted({o.get("type", "") for o in node["oneOf"]}))
    lines.append(f"  type:       {t}")
    enum = node.get("enum") or (node.get("items") or {}).get("enum")
    if enum:
        lines.append(f"  allowed:    {', '.join(str(e) for e in enum)}")
    if "minimum" in node or "maximum" in node:
        lines.append(f"  range:      {node.get('minimum', '…')}–{node.get('maximum', '…')}")
    if "default" in node:
        d = node["default"]
        lines.append(f"  default:    {str(d).lower() if isinstance(d, bool) else d}")
    if node.get("x-mutability"):
        lines.append(f"  changes:    {MUTABILITY.get(node['x-mutability'], node['x-mutability'])}")
    if node.get("x-api"):
        lines.append(f"  API:        {node['x-api']}")
    examples = node.get("examples")
    if examples:
        lines.append(f"  example:    {path.split('.')[-1]}: {examples[0]}")
    return "\n".join(lines)


def field_tree() -> str:
    lines = ["capella.yaml fields (capellactl help config <field> for details):", ""]
    for path, node in schema_fields().items():
        depth = path.count(".")
        name = path.split(".")[-1]
        t = node.get("type", "value")
        if t == "array" and isinstance(node.get("items"), dict) and node["items"].get("type") == "object":
            t = "list"
        mark = {"immutable": "  [immutable]", "key": "  [key]", "replace": "  [re-create]"}.get(
            node.get("x-mutability", ""), "")
        lines.append(f"{'  ' * depth}{name}: {t}{mark}")
    return "\n".join(lines)


# ------------------------------------------------------------------ commands
def _resolve_command(ctx: click.Context, words: list[str]) -> tuple[click.Command, click.Context] | None:
    root_ctx = ctx.find_root()
    cmd: click.Command = root_ctx.command
    parent = click.Context(cmd, info_name=root_ctx.info_name)
    for w in words:
        if not isinstance(cmd, click.Group):
            return None
        sub = cmd.get_command(parent, w)
        if sub is None:
            return None
        parent = click.Context(sub, info_name=w, parent=parent)
        cmd = sub
    return cmd, parent


@click.command("help", epilog="\b\nExamples:\n  capellactl help\n  capellactl help cluster scale\n"
                              "  capellactl help topics\n  capellactl help scaling\n"
                              "  capellactl help config clusters.serviceGroups.numOfNodes")
@click.argument("words", nargs=-1)
@click.pass_context
def help_cmd(ctx: click.Context, words: tuple[str, ...]) -> None:
    """Help for commands, concepts (topics) and every config field."""
    w = list(words)
    if not w:
        root_ctx = ctx.find_root()
        out(root_ctx.command.get_help(click.Context(root_ctx.command, info_name=root_ctx.info_name)))
        out("")
        out(GETTING_STARTED)
        out("Topics (capellactl help <topic>):")
        for name, summary in TOPICS.items():
            out(f"  {name:<16} {summary}")
        return
    if w == ["topics"]:
        for name, summary in TOPICS.items():
            out(f"  {name:<16} {summary}")
        return
    if w[0] == "config":
        if len(w) == 1:
            render_markdown(topic_text("config"))
            out("")
            out(field_tree())
            return
        wanted = normalize_field_path(w[1])
        fields = schema_fields()
        if wanted in fields:
            out(field_detail(wanted, fields[wanted]))
            return
        close = difflib.get_close_matches(wanted, list(fields), n=3, cutoff=0.5)
        if not close:
            last = wanted.split(".")[-1]
            close = [f for f in fields if f.endswith("." + last) or f == last][:3]
        msg = f"unknown config field '{w[1]}'."
        if close:
            msg += " Did you mean: " + ", ".join(close) + "?"
        raise CliExit(ExitCode.CHANGES, msg)
    resolved = _resolve_command(ctx, w)
    if resolved is not None:
        cmd, sub_ctx = resolved
        out(cmd.get_help(sub_ctx))
        return
    if len(w) == 1 and w[0] in TOPICS:
        render_markdown(topic_text(w[0]))
        return
    root = ctx.find_root().command
    candidates = list(TOPICS)
    if isinstance(root, click.Group):
        candidates += root.list_commands(ctx)
        if len(w) > 1:
            parent = _resolve_command(ctx, w[:-1])
            if parent and isinstance(parent[0], click.Group):
                candidates += parent[0].list_commands(parent[1])
    match = difflib.get_close_matches(w[-1], candidates, n=1)
    hint = f" Did you mean '{match[0]}'?" if match else ""
    kind = "command or topic"
    raise CliExit(ExitCode.CHANGES, f"unknown {kind} '{' '.join(w)}'.{hint} Topics: {', '.join(TOPICS)}")


@click.command(epilog="\b\nExamples:\n  capellactl completion zsh >> ~/.zshrc\n"
                      "  capellactl completion bash > /etc/bash_completion.d/capellactl")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
@click.pass_context
def completion(ctx: click.Context, shell: str) -> None:
    """Print a shell completion script."""
    cls = get_completion_class(shell)
    assert cls is not None
    root = ctx.find_root()
    out(cls(root.command, {}, "capellactl", "_CAPELLACTL_COMPLETE").source())

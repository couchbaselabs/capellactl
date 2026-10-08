"""click Group with 'did you mean' suggestions, used by every command group (CAP-034 AC2)."""

from __future__ import annotations

import difflib
from typing import Any

import click


class SuggestingGroup(click.Group):
    def resolve_command(self, ctx: click.Context, args: list[str]) -> Any:
        name = args[0] if args else None
        if name and not name.startswith("-") and self.get_command(ctx, name) is None:
            match = difflib.get_close_matches(name, self.list_commands(ctx), n=1)
            hint = f" Did you mean '{match[0]}'?" if match else ""
            raise click.UsageError(f"unknown command '{name}'.{hint}", ctx)
        return super().resolve_command(ctx, args)

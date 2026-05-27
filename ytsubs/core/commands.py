from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


CommandHandler = Callable[[list[str]], None]
AccessRule = bool | Callable[[list[str]], bool]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: CommandHandler
    help: str
    addon_name: str | None = None
    access_controlled: AccessRule = False

    def requires_access(self, args: list[str]) -> bool:
        if callable(self.access_controlled):
            return self.access_controlled(args)
        return self.access_controlled


class CommandRegistry:
    """Registers both application and addon commands for dispatch."""

    def __init__(self) -> None:
        self.commands: dict[str, CommandSpec] = {}

    def command(
        self,
        name: str,
        handler: CommandHandler,
        help: str,
        addon_name: str | None = None,
        *,
        access_controlled: AccessRule = False,
    ) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("command name cannot be empty")
        if key in self.commands:
            raise ValueError(f"command {key!r} already registered")
        self.commands[key] = CommandSpec(key, handler, help, addon_name, access_controlled)


# Public compatibility name for addons written against the extension API.
AddonRegistry = CommandRegistry

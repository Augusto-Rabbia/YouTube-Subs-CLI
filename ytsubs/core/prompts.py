from __future__ import annotations

from typing import Callable


Validator = Callable[[str], bool]


class SetupPrompts:
    """Input/output helpers shared by app setup and optional feature setup."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] | None = None,
        print_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._input = input_fn or input
        self._print = print_fn or print
        self._deferred: list[Callable[[], None]] = []

    def input(self, prompt: str) -> str:
        return self._input(prompt)

    def print(self, message: str = "") -> None:
        self._print(message)

    def ask_yes_no(self, prompt: str, default: bool) -> bool:
        suffix = " [Y/n]: " if default else " [y/N]: "
        while True:
            value = self.input(prompt + suffix).strip().lower()
            if not value:
                return default
            if value in {"y", "yes"}:
                return True
            if value in {"n", "no"}:
                return False
            self.print("Please enter `y` or `n`.")

    def ask_choice(self, prompt: str, options: set[str], default: str) -> str:
        while True:
            value = self.input(prompt).strip().lower() or default
            if value in options:
                return value
            self.print("Choose one of: " + ", ".join(sorted(options)) + ".")

    def ask_validated(
        self,
        prompt: str,
        default: str,
        validator: Validator,
        error: str,
    ) -> str:
        while True:
            value = self.input(prompt).strip() or default
            if validator(value):
                return value
            self.print(error)

    def defer(self, action: Callable[[], None]) -> None:
        self._deferred.append(action)

    def finish(self) -> None:
        actions, self._deferred = self._deferred, []
        for action in actions:
            action()

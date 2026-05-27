from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .models import ChannelCandidate
from .prompts import SetupPrompts
from .util import CHANNEL_ID_RE

if TYPE_CHECKING:
    from .app import App


@dataclass(frozen=True)
class ChannelLookup:
    spec: str
    candidate: ChannelCandidate | None = None
    choices: tuple[ChannelCandidate, ...] = ()
    error: str | None = None


class SetupWizard:
    def __init__(
        self,
        app: App,
        *,
        input_fn: Callable[[str], str] = input,
        print_fn: Callable[[str], None] = print,
    ) -> None:
        self.app = app
        self.ui = SetupPrompts(input_fn=input_fn, print_fn=print_fn)
        self.input = self.ui.input
        self.print = self.ui.print

    def is_complete(self) -> bool:
        return self.app.store.get_config("core", "setup_complete", "off") == "on"

    def run(self, *, require_confirmation: bool = False) -> bool:
        executor: ThreadPoolExecutor | None = None
        lookups: list[tuple[str, Future[ChannelLookup]]] = []
        try:
            if require_confirmation:
                answer = self.input(
                    "Running setup again can change subscriptions, download preferences, and addon settings. "
                    "Type `ok` to continue: "
                ).strip().lower()
                if answer != "ok":
                    self.print("Setup cancelled.")
                    return False
            self.print("")
            self.print("YTSubs Setup")
            self.print("============")
            self.print("This wizard prepares your subscriptions, downloads, and optional viewing controls.")
            specs = self.collect_channel_specs()
            executor, lookups = self.start_channel_lookups(specs)
            self.configure_download()
            self.configure_addons()
            self.finish_channel_lookups(lookups)
            self.ui.finish()
            self.app.store.set_config("core", "setup_complete", "on")
            self.print("")
            self.print("Setup complete. Run `new` to see unwatched uploads or `latest 10` to browse recent videos.")
            return True
        except (EOFError, KeyboardInterrupt):
            self.print("\nSetup cancelled before completion. Run `setup` to continue later.")
            return False
        finally:
            if executor is not None:
                executor.shutdown(wait=True)

    def collect_channel_specs(self) -> list[str]:
        self.print("")
        self.print("1. Subscriptions")
        self.print("Enter the channels you want to follow, separated by commas.")
        self.print("Use an @handle, channel ID, URL, or plain channel name.")
        value = self.input("Channels: ")
        return [spec.strip() for spec in value.split(",") if spec.strip()]

    def start_channel_lookups(
        self, specs: list[str]
    ) -> tuple[ThreadPoolExecutor | None, list[tuple[str, Future[ChannelLookup]]]]:
        if not specs:
            self.print("No channels entered. You can add subscriptions later with `sub add`.")
            return None, []
        self.print(f"Looking up {len(specs)} channel(s) in the background while setup continues...")
        executor = ThreadPoolExecutor(max_workers=min(6, len(specs)))
        futures = [(spec, executor.submit(self.lookup_channel, spec)) for spec in specs]
        return executor, futures

    def lookup_channel(self, spec: str) -> ChannelLookup:
        direct = (
            spec.startswith("@")
            or bool(CHANNEL_ID_RE.fullmatch(spec))
            or "://" in spec
            or "youtube.com/" in spec
        )
        try:
            if direct:
                return ChannelLookup(spec=spec, candidate=self.app.yt.resolve_channel(spec))
            choices = self.app.yt.search_channels(spec, limit=5)
        except Exception as exc:
            return ChannelLookup(spec=spec, error=str(exc))

        if not choices:
            return ChannelLookup(spec=spec, error="no channels found")
        if len(choices) == 1:
            return ChannelLookup(spec=spec, candidate=choices[0])
        return ChannelLookup(spec=spec, choices=tuple(choices))

    def finish_channel_lookups(self, lookups: list[tuple[str, Future[ChannelLookup]]]) -> None:
        if not lookups:
            return
        self.print("")
        self.print("Almost done. Finishing subscription setup...")
        results = [(spec, future.result()) for spec, future in lookups]
        if any(result.choices for _, result in results):
            self.print("Some channels have multiple matches. Choose which channel to add for each one.")
        added = 0
        for spec, result in results:
            candidate = result.candidate
            if candidate is None and result.choices:
                candidate = self.choose_channel(result)
            if candidate is None:
                self.print(f"Could not add {spec!r}: {result.error or 'no selection made'}.")
                continue
            if self.app.store.add_subscription(candidate):
                added += 1
                label = candidate.handle or candidate.channel_id
                self.print(f"Subscribed to {candidate.title} ({label}).")
            else:
                self.print(f"Already subscribed to {candidate.title}.")
        if added:
            self.print("Fetching initial uploads from your new subscriptions...")
            self.app.refresh_silent(force=True)

    def choose_channel(self, lookup: ChannelLookup) -> ChannelCandidate | None:
        self.print(f"Multiple channels match {lookup.spec!r}:")
        for position, candidate in enumerate(lookup.choices, 1):
            label = candidate.handle or candidate.channel_id
            self.print(f"  {position}. {candidate.title} ({label})")
        while True:
            value = self.input("Choose a number, or press Enter to skip: ").strip()
            if not value:
                return None
            if value.isdigit() and 1 <= int(value) <= len(lookup.choices):
                return lookup.choices[int(value) - 1]
            self.print("Enter one of the listed numbers, or press Enter to skip.")

    def configure_addons(self) -> None:
        self.print("")
        self.print("3. Addons")
        self.print("Choose the features that should shape your YouTube experience.")
        for addon in self.app.addons.installed():
            self.print("")
            self.print(f"{addon.name}: {addon.description}")
            addon.setup(self.ui)

    def configure_download(self) -> None:
        self.print("")
        self.print("2. Downloads")
        self.print("Configure built-in offline viewing.")
        self.app.download.setup(self.ui)

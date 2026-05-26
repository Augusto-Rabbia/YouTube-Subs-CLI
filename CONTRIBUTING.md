# Contributing

## Local setup

```bash
./scripts/setup_linux.sh
```

## Code standards

- Keep core orchestration in `ytsubs/core/app.py`.
- Keep persistence in `ytsubs/core/store.py`.
- Keep external integration code isolated.
- Prefer addons over new core commands when the feature is optional.
- Obtain app state paths through `ytsubs.core.paths`; supported runs keep state under the configured portable application root.
- Do not add background daemons.
- Do not add browser automation.

## Addon standards

- Use `BaseAddon`.
- Store persistent settings through `addon_config`.
- Store disposable state through `addon_cache`.
- Register commands with `addon_name=self.name`.
- Avoid global mutable state.

## Validation

Run:

```bash
./.venv/bin/python -m compileall -q ytsubs
./scripts/run_linux.sh --version
./scripts/run_linux.sh addon list
./scripts/run_linux.sh download cfg
docker compose config --quiet
```

# packrat

A single-file FTP backup CLI. Downloads a remote folder over plain FTP with
rich progress UI, optionally zipping it into a datestamped archive
(`2026-08-10-1432-<slug>.zip`). Generic by design — never make it
game-specific.

## Layout

- `packrat.py` — the entire application (pure helpers, FTP layer, `run_backup`
  orchestration, argparse + rich CLI in `main`). There are no other modules;
  keep it that way unless the file becomes unmanageable.
- `test_packrat.py` — all tests, including the pyftpdlib server fixtures.
- `.github/workflows/release.yml` — CI. Runs only on `v*` tags: tests on
  macOS + Windows, PyInstaller binaries attached to the GitHub release.
- `.claude/skills/cut-release/` — skill that automates cutting a release.

## Commands

Dependencies are managed by uv; there is no setup step.

```sh
uv run pytest                                        # run the test suite
uv run python packrat.py --help                      # run the CLI from source
uv run pyinstaller --onefile --name packrat packrat.py   # build a binary
```

## Rules

- TDD: write the failing test first, then the code. Every behavior change
  needs a test.
- FTP-facing code is tested against the real local FTP server fixtures
  (`ftp_server` / `ftp_conn` in `test_packrat.py`), never mocks.
- Gotcha worth knowing: `NLST` resets the FTP transfer type to ASCII, and many
  servers refuse `SIZE` in ASCII mode — that's why `_walk_nlst` re-asserts
  `TYPE I` before each `SIZE`. Cheap game-host servers often lack MLSD, so
  the NLST fallback path matters; don't break it.
- CI does not run on pushes or PRs — run `uv run pytest` locally before
  pushing.
- Keep stdout/UI code (rich) inside `main`; everything else stays importable
  and testable without a terminal.

## Cutting a release

Use the `cut-release` skill (`/cut-release`), or manually: bump `version` in
`pyproject.toml`, commit and push to `main`, then tag `vX.Y.Z` (matching the
pyproject version) and push the tag. CI builds and attaches
`packrat-macos-arm64` and `packrat-windows.exe`; the release body (including
macOS Gatekeeper instructions) is set by the workflow. Verify both assets
landed with `gh release view vX.Y.Z`.

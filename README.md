# packrat

A simple FTP backup CLI. Downloads a folder from an FTP server with pretty
progress bars, and optionally zips it into a single datestamped archive like
`2026-08-10-1432-valheim.zip`. Built for game-server backups (Valheim, etc.)
but generic — it just copies a remote folder.

## Usage

```sh
packrat --host 203.0.113.7 --port 31931 --user gpftp123 \
        --remote /save-data --dest ~/backups \
        --zip --slug valheim
```

| Option | Meaning |
|---|---|
| `--host` | FTP server hostname or IP |
| `--port` | FTP port (default 21) |
| `--user` | FTP username |
| `--password` | FTP password (see below for safer options) |
| `--env-file` | Path to a `.env` file with credentials |
| `--remote` | Source folder on the server |
| `--dest` | Destination folder on this machine |
| `--zip` | Zip the download into one archive, delete the temp files |
| `--slug` | Name in the zip filename (default `backup`) |

Without `--zip`, each run downloads into a dated subfolder
(`dest/2026-08-10-1432/`). With `--zip`, the download is staged in a temp
directory, zipped to `dest/2026-08-10-1432-<slug>.zip`, and the temp files are
removed — the zip is the artifact. Reruns never overwrite anything: the
timestamp in the name makes every run unique.

### Passwords

Three options, in order of precedence:

1. `--password hunter2` — easiest, but lands in your shell history.
2. `--env-file backups.env` — a file containing `FTP_PASSWORD=hunter2`
   (it can also hold `FTP_HOST`, `FTP_PORT`, `FTP_USER`).
3. Neither — packrat prompts for the password interactively (hidden input).

Note: plain FTP sends your password unencrypted. That's a limitation of the
protocol your host offers, not something packrat can fix.

### Mid-write warning

If files on the server change while packrat is downloading (e.g. the game
server saved its world mid-transfer), packrat warns you afterwards so you can
re-run — a file copied while it's being rewritten may be corrupt.

## Install

Grab a prebuilt binary from [Releases](../../releases):

- `packrat-macos-arm64` — macOS on Apple Silicon
- `packrat-windows.exe` — Windows x64

On macOS: `chmod +x packrat-macos-arm64`, and on first run you may need to
clear quarantine: `xattr -d com.apple.quarantine packrat-macos-arm64`.

## Run from source

Requires [uv](https://docs.astral.sh/uv/):

```sh
uv run packrat.py --help
```

## Build a binary yourself

```sh
uv run pyinstaller --onefile --name packrat packrat.py
# → dist/packrat (or dist\packrat.exe on Windows)
```

PyInstaller can't cross-compile — build on the OS you're targeting. Tagged
pushes (`v*`) build both binaries in GitHub Actions and attach them to the
release.

## Tests

```sh
uv run pytest
```

Tests run against a real local FTP server (pyftpdlib), including a fallback
path for servers without MLSD support and a check that mid-download file
changes are detected.

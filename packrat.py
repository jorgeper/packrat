"""packrat — a simple FTP backup CLI.

Downloads a remote folder over plain FTP, optionally zipping it into a
datestamped archive like 2026-08-10-1432-valheim.zip.
"""

import argparse
import fnmatch
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Callable

Snapshot = dict[str, tuple[int, str]]


@dataclass
class BackupResult:
    artifact: Path
    files: int = 0
    total_bytes: int = 0
    changed: list[str] = field(default_factory=list)


def archive_name(now: datetime, slug: str) -> str:
    return f"{now:%Y-%m-%d-%H%M}-{slug}.zip"


def run_dirname(now: datetime) -> str:
    return f"{now:%Y-%m-%d-%H%M}"


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def resolve_credential(cli_value: str | None, env: dict[str, str], key: str) -> str | None:
    if cli_value is not None:
        return cli_value
    return env.get(key)


def walk_remote(ftp: FTP, root: str) -> Snapshot:
    """Recursively list files under root as {relative_path: (size, mtime)}."""
    root = root.rstrip("/") or "/"
    out: Snapshot = {}
    try:
        _walk_mlsd(ftp, root, "", out)
    except error_perm:
        out = {}
        _set_binary(ftp)
        _walk_nlst(ftp, root, "", out)
    return out


def _walk_mlsd(ftp: FTP, path: str, rel: str, out: Snapshot) -> None:
    # No explicit facts list: requesting one makes ftplib send OPTS MLST,
    # which some game-host servers reject even though plain MLSD works.
    for name, facts in ftp.mlsd(path):
        kind = facts.get("type")
        if kind == "dir":
            _walk_mlsd(ftp, f"{path}/{name}", f"{rel}{name}/", out)
        elif kind == "file":
            out[rel + name] = (int(facts.get("size", 0)), facts.get("modify", "?"))


def _walk_nlst(ftp: FTP, path: str, rel: str, out: Snapshot) -> None:
    for entry in ftp.nlst(path):
        name = entry.rsplit("/", 1)[-1]
        if name in (".", ".."):
            continue
        full = f"{path}/{name}"
        try:
            # NLST resets the transfer type to ASCII, and many servers
            # (pyftpdlib included) refuse SIZE in ASCII mode.
            _set_binary(ftp)
            size = ftp.size(full)
        except error_perm:
            size = None
        if size is None:
            _walk_nlst(ftp, full, f"{rel}{name}/", out)
        else:
            try:
                mtime = ftp.voidcmd(f"MDTM {full}")[4:].strip()
            except error_perm:
                mtime = "?"
            out[rel + name] = (size, mtime)


def _set_binary(ftp: FTP) -> None:
    try:
        ftp.voidcmd("TYPE I")
    except error_perm:
        pass


def download_tree(
    ftp: FTP,
    root: str,
    dest: Path,
    snapshot: Snapshot,
    on_bytes: Callable[[int], None] | None = None,
) -> None:
    """Download every file in snapshot under root into dest, preserving structure."""
    root = root.rstrip("/") or "/"
    dest = Path(dest)
    _set_binary(ftp)
    for rel in sorted(snapshot):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:

            def write(chunk: bytes) -> None:
                fh.write(chunk)
                if on_bytes is not None:
                    on_bytes(len(chunk))

            ftp.retrbinary(f"RETR {root}/{rel}", write)


def zip_directory(src: Path, target: Path) -> None:
    src = Path(src)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in src.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(src).as_posix())


def diff_snapshots(
    before: dict[str, tuple[int, str]], after: dict[str, tuple[int, str]]
) -> list[str]:
    return sorted(
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    )


def _matches(path: str, pattern: str) -> bool:
    # rsync-style: a pattern without "/" matches the filename anywhere in the
    # tree; a pattern containing "/" matches the full relative path.
    target = path if "/" in pattern else path.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(target, pattern)


def filter_snapshot(
    snapshot: Snapshot, includes: list[str], excludes: list[str]
) -> Snapshot:
    """Apply include/exclude globs. No includes = keep all; excludes win."""
    return {
        path: entry
        for path, entry in snapshot.items()
        if (not includes or any(_matches(path, p) for p in includes))
        and not any(_matches(path, p) for p in excludes)
    }


def run_backup(
    ftp: FTP,
    remote: str,
    dest: Path,
    slug: str = "backup",
    zip_mode: bool = False,
    now: datetime | None = None,
    on_bytes: Callable[[int], None] | None = None,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
) -> BackupResult:
    """Download remote into dest — as a dated subfolder, or a datestamped zip."""
    now = now or datetime.now()
    includes, excludes = includes or [], excludes or []
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    before = filter_snapshot(walk_remote(ftp, remote), includes, excludes)

    if zip_mode:
        staging = Path(tempfile.mkdtemp(prefix="packrat-"))
        artifact = dest / archive_name(now, slug)
    else:
        staging = dest / run_dirname(now)
        artifact = staging

    try:
        download_tree(ftp, remote, staging, before, on_bytes=on_bytes)
        after = filter_snapshot(walk_remote(ftp, remote), includes, excludes)
        changed = diff_snapshots(before, after)
        if zip_mode:
            zip_directory(staging, artifact)
    finally:
        if zip_mode:
            shutil.rmtree(staging, ignore_errors=True)

    return BackupResult(
        artifact=artifact,
        files=len(before),
        total_bytes=sum(size for size, _ in before.values()),
        changed=changed,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packrat",
        description="Download a folder from an FTP server, optionally zipping it "
        "into a datestamped archive.",
    )
    parser.add_argument("--host", help="FTP server hostname or IP")
    parser.add_argument("--port", type=int, default=21, help="FTP port (default: 21)")
    parser.add_argument("--user", help="FTP username")
    parser.add_argument("--password", help="FTP password (omit to use --env-file or be prompted)")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Path to a .env file with FTP_HOST / FTP_PORT / FTP_USER / FTP_PASSWORD",
    )
    parser.add_argument("--remote", help="Source folder on the server, e.g. /save-data")
    parser.add_argument("--dest", type=Path, help="Destination folder on this machine")
    parser.add_argument("--zip", action="store_true", help="Zip the download into a single archive")
    parser.add_argument(
        "--slug", default="backup", help="Name used in the zip file (default: backup)"
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="Only download files matching this glob (repeatable). "
        "Without '/', matches filenames anywhere; with '/', matches the path relative to --remote.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Skip files matching this glob (repeatable; wins over --include)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
        TransferSpeedColumn,
    )
    from rich.prompt import Prompt

    console = Console()
    args = build_parser().parse_args(argv)

    env = load_env_file(args.env_file) if args.env_file else {}
    host = resolve_credential(args.host, env, "FTP_HOST")
    port = int(resolve_credential(str(args.port) if args.port != 21 else None, env, "FTP_PORT") or 21)
    user = resolve_credential(args.user, env, "FTP_USER")
    password = resolve_credential(args.password, env, "FTP_PASSWORD")

    missing = [name for name, value in [("--host", host), ("--user", user), ("--remote", args.remote), ("--dest", args.dest)] if not value]
    if missing:
        console.print(f"[red]Missing required options:[/] {', '.join(missing)}")
        return 2

    if password is None:
        password = Prompt.ask(f"Password for [bold]{user}@{host}[/]", password=True)

    console.print(
        Panel.fit(
            f"[bold cyan]packrat[/] · [bold]{user}[/]@[bold]{host}[/]:{port}\n"
            f"[dim]remote[/] {args.remote}  [dim]→ dest[/] {args.dest}"
            + (f"  [dim]· zip slug[/] [bold]{args.slug}[/]" if args.zip else ""),
            border_style="cyan",
        )
    )

    ftp = FTP()
    try:
        with console.status(f"Connecting to {host}:{port}..."):
            ftp.connect(host, port, timeout=30)
            ftp.login(user, password)
        console.print(f"[green]✓[/] Connected — {ftp.getwelcome().splitlines()[0]}")

        with console.status(f"Scanning [bold]{args.remote}[/]..."):
            found = walk_remote(ftp, args.remote)
        snapshot = filter_snapshot(found, args.include, args.exclude)
        total = sum(size for size, _ in snapshot.values())
        if args.include or args.exclude:
            console.print(
                f"[green]✓[/] Found [bold]{len(found)}[/] files, "
                f"[bold]{len(snapshot)}[/] match filters · {total / 1024:,.0f} KiB"
            )
        else:
            console.print(
                f"[green]✓[/] Found [bold]{len(snapshot)}[/] files · {total / 1024:,.0f} KiB"
            )
        if not snapshot:
            console.print("[yellow]Nothing to download.[/]")
            return 1

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading", total=total)
            result = run_backup(
                ftp,
                args.remote,
                args.dest,
                slug=args.slug,
                zip_mode=args.zip,
                on_bytes=lambda n: progress.update(task, advance=n),
                includes=args.include,
                excludes=args.exclude,
            )
    except error_perm as exc:
        console.print(f"[red]✗ FTP error:[/] {exc}")
        return 1
    except OSError as exc:
        console.print(f"[red]✗ Connection failed:[/] {exc}")
        return 1
    finally:
        try:
            ftp.quit()
        except Exception:
            pass

    if result.changed:
        console.print(
            Panel.fit(
                "[yellow bold]⚠ Files changed on the server during the download:[/]\n"
                + "\n".join(f"  · {name}" for name in result.changed)
                + "\n[yellow]The backup may be inconsistent — consider re-running.[/]",
                border_style="yellow",
            )
        )

    console.print(
        f"[green bold]✓ Done[/] — {result.files} files, "
        f"{result.total_bytes / 1024:,.0f} KiB → [bold]{result.artifact}[/]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

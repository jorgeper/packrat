---
name: cut-release
description: Cut a new packrat release — bump the version, tag, watch CI, and verify both binaries landed on the release page. Use when asked to cut, ship, or publish a release.
---

# Cut a packrat release

Releases are driven by `v*` tags: pushing a tag triggers
`.github/workflows/release.yml`, which runs the tests on macOS and Windows,
builds a PyInstaller binary on each, and attaches both to the GitHub release
with a prewritten body.

## Inputs

The user may name an explicit version ("cut 0.3.0") or a bump size ("cut a
patch release"). If they said neither, default to a **patch** bump and say so
in your summary. Read the current version from `pyproject.toml`.

## Steps

1. **Preflight.** Confirm you're on `main` with a clean working tree
   (`git status`), then `git pull`. If the tree is dirty, stop and ask —
   never release uncommitted work.
2. **Test.** Run `uv run pytest -q`. Any failure aborts the release; CI would
   fail on the tag anyway, but catching it here avoids a broken tag.
3. **Bump.** Edit `version` in `pyproject.toml` to the new version. Commit as
   `Bump version to X.Y.Z` and push to `main`.
4. **Tag.** `git tag vX.Y.Z && git push origin vX.Y.Z` — the `v` prefix is
   required; the tag must match the pyproject version.
5. **Watch CI.** Get the run for the tag with
   `gh run list --limit 1 --json databaseId -q '.[0].databaseId'` (allow a
   ~20s delay for it to appear), then `gh run watch --exit-status <id>`.
6. **Verify.** `gh release view vX.Y.Z --json assets` must list BOTH
   `packrat-macos-arm64` and `packrat-windows.exe`. Only then report success,
   with a link to the release page.

## If the build fails

Delete the tag so the version can be re-tagged after the fix:

```sh
git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z
```

Also delete the draft/partial release if one was created
(`gh release delete vX.Y.Z --yes`). Diagnose the CI failure
(`gh run view <id> --log-failed`), fix it on `main` (with a test, following
TDD), and start over from step 1. Do not leave the version bump commit
unreleased without telling the user.

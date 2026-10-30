# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## What this project is

`android-emu-squircle-icon` replaces the Android Emulator's circular Dock icon with a
macOS squircle by patching the PNGs embedded in the `qemu-system-*` binary. The
CLI is `bin/emu-icon` (`status`, `apply [--force]`, `restore`). Read the module
docstring of `lib/patch.py` first; it explains the whole approach.

## Hard constraints (do not break these)

- **macOS only.** No Linux/Windows code paths. `main()` rejects other platforms.
- **No third-party dependencies.** Python stdlib + system `/usr/bin/python3`,
  Swift via `swiftc` from the Xcode Command Line Tools.
- **Same-length patching.** Each replacement PNG must be padded to the exact
  byte length of the slot it replaces. Never change a length: the Qt resource
  table stores offsets and sizes elsewhere in the binary.
- **Keep the original entitlements** when re-signing, or the emulator cannot
  create VMs.
- **Never modify the SDK before the new binary is built, signed and verified.**
  Write to a temp file in the same directory, then `os.replace`.
- **Never hardcode icon offsets.** They change with every emulator version;
  `find_slots` discovers them.
- **Load PNG art as raw pixels** (ImageIO, not `NSImage`). The source PNGs carry
  an orientation chunk that `NSImage` applies and Qt ignores.

## Conventions

- Everything in the repo is in **English** (code, comments, docs). Chat with the
  maintainer may be in another language.
- **Generic paths only.** Use `$HOME` / `~` and the `ANDROID_HOME` discovery in
  `sdk_root()`. Never write a username, personal path or machine name into code,
  docs or fixtures.
- Comment the *why* (signing, same-length padding, EXIF rotation), not the
  *what*. Keep `lib/patch.py` module docstring and the README "How it works"
  in sync when behaviour changes.

## Testing a change

There is no test suite; verify against a real SDK:

```sh
bin/emu-icon status                 # finds the slots, reports state
bin/emu-icon apply --force          # renders, patches, signs
codesign --verify -v "$ANDROID_HOME/emulator/qemu/darwin-aarch64/qemu-system-aarch64"
bin/emu-icon restore && bin/emu-icon status   # must report the original icon
bin/emu-icon apply                  # re-apply
```

Then start an AVD (`$ANDROID_HOME/emulator/emulator -avd <name>`) and confirm it
boots. `apply` is idempotent: a second run prints `already applied`.
After editing `lib/round.swift` or `lib/encode.py`, regenerate the README image
with `docs/make-preview.sh` and look at it.

## Git

- Do not commit or push unless the maintainer asks in that turn. Approval to
  commit is not approval to push.
- Do not add `Co-Authored-By` trailers or AI attribution to commits or PRs.
- `backups/` and the compiled `lib/round` binary are git-ignored. Never commit
  Google's `qemu-system-*` binary.

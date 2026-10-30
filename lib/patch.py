"""android-emu-squircle: swap the Android Emulator's circular icon for a macOS squircle.

Background
----------
The Android Emulator on macOS runs as ``qemu-system-<arch>``, a bare Mach-O
executable (not an ``.app`` bundle). It has no ``.icns`` to replace: Qt sets the
Dock/window icon at runtime from PNG images compiled into the binary as Qt
resources (``emulator_icon_32.png``, ``emulator_icon_128.png``,
``emulator_icon_256.png``). Those images are a circular badge, which looks out
of place next to every other macOS icon.

What this script does
---------------------
1. Locate the SDK and the qemu binary.
2. Scan the binary for the three consecutive square PNGs (32, 128, 256 px).
   Offsets are discovered, never hardcoded, so SDK updates do not break it.
3. Render a squircle version of each icon (``lib/round.swift``) and encode it as a
   compact PNG (``lib/encode.py``).
4. Overwrite each embedded PNG *in place* with a replacement of the exact same
   byte length (see "Why same length" below).
5. Re-sign the binary ad hoc, keeping the original entitlements, and swap it in
   atomically.

Why same length
---------------
Qt resources are addressed by an offset/size table elsewhere in the binary. If a
replacement PNG were longer or shorter, every later offset would shift and the
table would be wrong. So each new PNG is padded up to the original length with
an ancillary ``tEXt`` chunk placed before ``IEND``. Decoders ignore ancillary
chunks, so the padding is invisible, and it carries a marker string (``MARK``)
that lets us detect an already-patched binary.

Why re-sign
-----------
The binary ships signed by Google with the hardened runtime. Editing bytes
invalidates that signature and macOS (Apple Silicon especially) refuses to run
a binary with a broken signature. An ad hoc signature (``codesign -s -``) is
enough to run locally, but the binary also needs its original entitlements
(JIT, unsigned executable memory, hypervisor, ...) or the emulator fails to boot
VMs, so they are dumped from the current binary and reapplied.

Safety
------
* The pristine binary is copied to ``backups/`` before the first patch (last 3
  kept).
* The new binary is written to a temp file next to the target, signed and
  verified *before* it replaces anything. ``os.replace`` is atomic, and running
  emulators keep the old inode, so they are not disturbed.
* If the PNG layout is not recognised or a replacement does not fit, the script
  aborts without touching the SDK.

Usage: ``emu-icon [status | apply [--force] | restore]`` (see README.md).
macOS only.
"""
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

# Root of this tool (the directory containing bin/, lib/, assets/, backups/).
HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HOME, "lib"))
import encode  # noqa: E402  (needs the sys.path entry above)

PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"IEND\xaeB`\x82"  # IEND chunk incl. length and CRC: the last 12 bytes of every PNG
MARK = b"emu-icon-squircle"  # written into the padding chunk to flag a patched binary
SIZES = (32, 128, 256)  # the icon sizes the emulator embeds, in storage order
BACKUP_DIR = os.path.join(HOME, "backups")  # created on demand; git does not track empty dirs
BACKUP_PREFIX = "qemu-system."
KEEP_BACKUPS = 3


def sdk_root():
    """Android SDK location: $ANDROID_HOME, then $ANDROID_SDK_ROOT, then the default."""
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            return os.environ[var]
    return os.path.expanduser("~/Library/Android/sdk")


def binary_path():
    """Path of the emulator's qemu binary for this machine's architecture.

    The SDK stores it as ``emulator/qemu/darwin-<arch>/qemu-system-<arch>`` where
    <arch> is ``aarch64`` on Apple Silicon and ``x86_64`` on Intel.
    """
    arch = "aarch64" if os.uname().machine == "arm64" else "x86_64"
    return os.path.join(sdk_root(), "emulator", "qemu", f"darwin-{arch}", f"qemu-system-{arch}")


def require_binary():
    path = binary_path()
    if not os.path.exists(path):
        raise SystemExit(f"error: emulator binary not found: {path}\n"
                         "Set ANDROID_HOME if your SDK is not in ~/Library/Android/sdk.")
    return path


def find_slots(data):
    """Locate the embedded icons and return ``[(offset, length), ...]`` for 32/128/256.

    Strategy: find every PNG signature, read its width/height from the IHDR
    chunk (bytes 16..24) and its end from the next IEND. Then look for three
    consecutive square PNGs whose sizes are exactly 32, 128 and 256 and that sit
    back to back (a small gap is tolerated for resource-table padding). That
    triple is how the emulator stores its window icon; other PNGs in the binary
    (skins, UI sprites) do not match.
    """
    pngs = []
    for match in re.finditer(re.escape(PNG_SIG), data):
        start = match.start()
        width, height = struct.unpack(">II", data[start + 16:start + 24])
        end = data.find(PNG_IEND, start)
        # Skip false positives (signature bytes inside other data) and absurd sizes.
        if end < 0 or width != height or width > 4096:
            continue
        pngs.append((start, end + len(PNG_IEND) - start, width))

    for i in range(len(pngs) - 2):
        a, b, c = pngs[i:i + 3]
        if (a[2], b[2], c[2]) != SIZES:
            continue
        adjacent = a[0] + a[1] <= b[0] < a[0] + a[1] + 64 and b[0] + b[1] <= c[0] < b[0] + b[1] + 64
        if adjacent:
            return [(p[0], p[1]) for p in (a, b, c)]
    raise SystemExit("error: could not find the 32/128/256 icon PNGs in the binary "
                     "(the emulator may have changed how it embeds the icon). Nothing was modified.")


def png_chunk(chunk_type, payload):
    """Serialise one PNG chunk: length, type, payload, CRC32 over type+payload."""
    return (struct.pack(">I", len(payload)) + chunk_type + payload
            + struct.pack(">I", zlib.crc32(chunk_type + payload)))


def render(size):
    """Render the squircle icon for ``size`` px and return it as PNG bytes.

    The Swift renderer is compiled once into ``lib/round`` (needs the Xcode
    Command Line Tools) and then reused. It reads ``assets/orig<size>.png`` and
    writes raw premultiplied RGBA, which ``encode.encode`` turns into a PNG.
    """
    renderer = os.path.join(HOME, "lib", "round")
    source = os.path.join(HOME, "lib", "round.swift")
    if not os.path.exists(renderer) or os.path.getmtime(renderer) < os.path.getmtime(source):
        print("compiling renderer (one time)...")
        subprocess.check_call(["swiftc", "-O", source, "-o", renderer])
    with tempfile.TemporaryDirectory() as tmp:
        raw_path = os.path.join(tmp, "icon.rgba")
        subprocess.check_call([renderer, os.path.join(HOME, "assets", f"orig{size}.png"), raw_path, str(size)])
        with open(raw_path, "rb") as f:
            return encode.encode(f.read(), size)


def fit_to_slot(png, slot_length, size):
    """Pad ``png`` with a ``tEXt`` chunk so it is exactly ``slot_length`` bytes.

    The padding chunk goes right before IEND. Its overhead is 12 bytes (length,
    type, CRC) plus the ``Comment\\0`` keyword (8 bytes) and the marker, so the
    replacement must leave at least that much room or it cannot be padded.
    """
    keyword = b"Comment\0"
    overhead = 12 + len(keyword) + len(MARK)
    pad = slot_length - len(png)
    if pad < overhead:
        raise SystemExit(f"error: the {size}px icon does not fit its slot "
                         f"({len(png)} bytes needed, {slot_length - overhead} available). Nothing was modified.")
    filler = b" " * (pad - 12 - len(keyword) - len(MARK))
    padded = png[:-12] + png_chunk(b"tEXt", keyword + MARK + filler) + png[-12:]
    assert len(padded) == slot_length
    return padded


def is_patched(data, slots):
    """True if every icon slot contains our marker."""
    return all(MARK in data[off:off + length] for off, length in slots)


def emulators_running():
    """True if an emulator VM process is alive (it must be restarted to show the new icon)."""
    result = subprocess.run(["pgrep", "-f", "qemu-system-.*-avd"], capture_output=True, text=True)
    return bool(result.stdout.split())


def sign_ad_hoc(path, original):
    """Ad hoc sign ``path`` with the hardened runtime and ``original``'s entitlements.

    Entitlements are read from ``original`` (the binary being replaced) so the
    patched build keeps exactly the capabilities Google granted it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        entitlements = os.path.join(tmp, "entitlements.plist")
        subprocess.run(["codesign", "-d", "--entitlements", ":" + entitlements, original], capture_output=True)
        args = ["codesign", "--force", "--sign", "-", "--options", "runtime"]
        if os.path.exists(entitlements) and os.path.getsize(entitlements):
            args += ["--entitlements", entitlements]
        subprocess.check_call(args + [path])
    subprocess.check_call(["codesign", "--verify", path])


def cmd_status():
    """Report where the binary is and whether the squircle icon is applied."""
    path = require_binary()
    with open(path, "rb") as f:
        data = f.read()
    slots = find_slots(data)
    print("binary :", path)
    print("slots  :", slots)
    print("state  :", "squircle icon applied" if is_patched(data, slots) else "original (circular) icon")
    print("running:", "yes (restart emulators to see changes)" if emulators_running() else "no")


def cmd_apply(force=False):
    """Patch the binary. A no-op when already patched unless ``force`` is set."""
    path = require_binary()
    with open(path, "rb") as f:
        data = bytearray(f.read())
    slots = find_slots(bytes(data))
    patched = is_patched(bytes(data), slots)
    if patched and not force:
        print("already applied (use --force to redo)")
        return

    if not patched:
        # Only back up a pristine binary; re-patching a patched one must not
        # overwrite the good backup with an already modified copy.
        os.makedirs(BACKUP_DIR, exist_ok=True)
        digest = hashlib.sha256(bytes(data)).hexdigest()[:12]
        backup = os.path.join(BACKUP_DIR, f"{BACKUP_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}.{digest}")
        shutil.copy2(path, backup)
        print("backup :", backup)
        old = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(BACKUP_PREFIX))
        for name in old[:-KEEP_BACKUPS]:
            os.remove(os.path.join(BACKUP_DIR, name))

    for (offset, length), size in zip(slots, SIZES):
        data[offset:offset + length] = fit_to_slot(render(size), length, size)

    # Write next to the target so os.replace is a same-filesystem atomic rename.
    tmp_path = os.path.join(os.path.dirname(path), ".qemu-icon-tmp")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, 0o755)
        sign_ad_hoc(tmp_path, path)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    print("applied. Restart running emulators to see the new icon "
          "(run `killall Dock` if the Dock keeps the old one).")


def cmd_restore():
    """Put back the most recent pristine backup (see README for the SDK-update caveat)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(BACKUP_PREFIX))
    if not backups:
        raise SystemExit("error: no backups found")
    source = os.path.join(BACKUP_DIR, backups[-1])
    path = require_binary()
    tmp_path = os.path.join(os.path.dirname(path), ".qemu-icon-tmp")
    try:
        shutil.copy2(source, tmp_path)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    print("restored from", source)


def main(argv):
    if sys.platform != "darwin":
        raise SystemExit("error: android-emu-squircle only supports macOS.")
    command = argv[1] if len(argv) > 1 else "status"
    if command == "status":
        cmd_status()
    elif command == "apply":
        cmd_apply(force="--force" in argv)
    elif command == "restore":
        cmd_restore()
    else:
        raise SystemExit("usage: emu-icon [status | apply [--force] | restore]")


if __name__ == "__main__":
    main(sys.argv)

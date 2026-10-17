#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["hidapi", "typer"]
# ///
"""rkkb: remap Royal Kludge keyboard keys from the command line, no browser.

A local port of Kludge Knight's key-remap path (https://github.com/vinc3m1/kludgeknight,
GPL-3.0; its BufferCodec derives from Rangoli). Keyboard layouts come from that repo's
copy of RK's own config files, so clone it next to this script.

The firmware can only be written, never read: every write sends the whole keymap,
built from RK's defaults plus the overrides saved in ~/.config/rkkb/<pid>.json.
"""

import json
import os
import re
from pathlib import Path

import typer

RK_VID = 0x258A
CONFIG_USAGE_PAGE, CONFIG_USAGE = 0x0001, 0x0080  # the interface Kludge Knight writes to
NUM_BUFFERS, BUFFER_SIZE, BYTES_PER_KEY = 9, 65, 4
REPORT_ID = 0x0A

KK_ROOT = Path(os.environ.get("KLUDGEKNIGHT_DIR", Path.home() / "gits/kludgeknight"))
STATE_DIR = Path.home() / ".config/rkkb"

# Modifier flags in RK firmware codes (Kludge Knight CLAUDE.md, from USB captures).
# In Mac mode (Fn+S on the S70) the firmware sends Win as Cmd and Alt as Option.
MODIFIERS = {"ctrl": 0x010000, "shift": 0x020000, "alt": 0x040000, "opt": 0x040000,
             "cmd": 0x080000, "win": 0x080000}

# USB HID keyboard usages; a plain key's firmware code is usage << 8.
HID = {chr(ord("a") + i): 0x04 + i for i in range(26)}
HID |= {str((i + 1) % 10): 0x1E + i for i in range(10)}
HID |= {f"f{i + 1}": 0x3A + i for i in range(12)} | {f"f{i + 13}": 0x68 + i for i in range(12)}
HID |= {"enter": 0x28, "esc": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
        "minus": 0x2D, "equal": 0x2E, "lbracket": 0x2F, "rbracket": 0x30, "backslash": 0x31,
        "semicolon": 0x33, "quote": 0x34, "grave": 0x35, "comma": 0x36, "period": 0x37,
        "slash": 0x38, "capslock": 0x39, "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48,
        "insert": 0x49, "home": 0x4A, "pageup": 0x4B, "delete": 0x4C, "end": 0x4D,
        "pagedown": 0x4E, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52}


def parse_target(spec: str) -> int:
    """'f13', 'cmd+c', 'ctrl+shift+4' or a raw firmware code like '0x6800'."""
    if spec.lower().startswith("0x"):
        return int(spec, 16)
    *mods, key = spec.lower().split("+")
    if key not in HID:
        raise typer.BadParameter(f"unknown key {key!r}; known: {', '.join(sorted(HID))}")
    code = HID[key] << 8
    for m in mods:
        if m not in MODIFIERS:
            raise typer.BadParameter(f"unknown modifier {m!r}; known: {', '.join(MODIFIERS)}")
        code |= MODIFIERS[m]
    return code


def vk_firmware_table() -> dict[int, int]:
    """Windows VK code -> RK firmware code, read from Kludge Knight's keycode.ts."""
    src = (KK_ROOT / "src/types/keycode.ts").read_text()
    return {int(vk, 16): int(fw, 16)
            for vk, fw in re.findall(r"^\s*(0x[0-9A-Fa-f]+):\s*\{\s*vk:\s*0x[0-9a-fA-F]+,\s*fw:\s*(0x[0-9A-Fa-f]+)", src, re.M)}


def read_kb_ini(pid: int) -> str:
    for name in (f"{pid:04X}", f"{pid:04x}"):
        path = KK_ROOT / "public/rk/Dev" / name / "KB.ini"
        if path.exists():
            raw = path.read_bytes()
            utf16 = raw[:2] == b"\xff\xfe" or (len(raw) > 3 and (raw[1] == 0 or raw[3] == 0))
            return raw.decode("utf-16-le" if utf16 else "utf-8", errors="replace")
    raise typer.BadParameter(f"no KB.ini for PID {pid:04X} under {KK_ROOT}/public/rk/Dev")


def load_layout(pid: int) -> list[dict]:
    """Keys from KB.ini: [KEY] entries are left,top,right,bottom,flags,vk,fw,bIndex; the
    preceding ';label' comment names the key."""
    fw_of_vk = vk_firmware_table()
    keys, label, in_keys = [], "", False
    for line in read_kb_ini(pid).splitlines():
        line = line.strip()
        if line.startswith("["):
            in_keys = line.upper() == "[KEY]"
        elif in_keys and line.startswith(";"):
            label = line[1:].strip()
        elif in_keys and re.match(r"K\d+=", line):
            parts = [p.strip() for p in line.split("=", 1)[1].split(",")]
            if len(parts) != 8:
                continue
            vk, fallback = int(parts[5], 16), int(parts[6], 16)
            default = fw_of_vk.get(vk) or fallback
            if not default:
                continue  # Kludge Knight skips keys it has no firmware code for, so do we
            keys.append({"label": label, "slot": int(parts[7]), "vk": vk, "default": default,
                         "x": int(parts[0]), "y": int(parts[1])})
    return keys


def side_keys(keys: list[dict]) -> dict[str, int]:
    """m1..mN = the leftmost column, top to bottom (the S70's macro column)."""
    left = min(k["x"] for k in keys)
    column = sorted((k for k in keys if k["x"] - left < 20), key=lambda k: k["y"])
    return {f"m{i + 1}": k["slot"] for i, k in enumerate(column)}


def encode(keys: list[dict], overrides: dict[int, int]) -> list[bytes]:
    """Kludge Knight's BufferCodec.encode: 4 bytes per slot, big-endian within the slot,
    packed into 9 reports; report 1 carries 0x01 0xf8 after its 3-byte header."""
    full = bytearray(NUM_BUFFERS * BUFFER_SIZE)
    for k in keys:
        off = k["slot"] * BYTES_PER_KEY
        full[off:off + 4] = overrides.get(k["slot"], k["default"]).to_bytes(4, "big")
    out, pos = [], 0
    for i in range(NUM_BUFFERS):
        buf = bytearray(BUFFER_SIZE)
        buf[0:3] = bytes([REPORT_ID, NUM_BUFFERS, i + 1])
        start = 3
        if i == 0:
            buf[3:5] = b"\x01\xf8"
            start = 5
        n = BUFFER_SIZE - start
        buf[start:] = full[pos:pos + n]
        pos += n
        out.append(bytes(buf))
    return out


def config_interface(pid: int | None):
    import hid
    found = [d for d in hid.enumerate(RK_VID, 0)
             if d["usage_page"] == CONFIG_USAGE_PAGE and d["usage"] == CONFIG_USAGE
             and (pid is None or d["product_id"] == pid)]
    if not found:
        raise typer.Exit(f"no RK keyboard config interface found (VID {RK_VID:04X}); connect it by USB")
    if len(found) > 1 and pid is None:
        raise typer.Exit("several RK keyboards found; pass --pid")
    return found[0]


def state_path(pid: int) -> Path:
    return STATE_DIR / f"{pid:04X}.json"


def load_state(pid: int) -> dict[int, int]:
    p = state_path(pid)
    return {int(k): v for k, v in json.loads(p.read_text()).items()} if p.exists() else {}


app = typer.Typer(add_completion=False, help=__doc__)


@app.command("list")
def list_devices():
    """RK keyboards on USB that expose the remap interface."""
    import hid
    for d in hid.enumerate(RK_VID, 0):
        if d["usage_page"] == CONFIG_USAGE_PAGE and d["usage"] == CONFIG_USAGE:
            print(f"PID {d['product_id']:04X}  {d['product_string']}  {d['path'].decode()}")


@app.command()
def keys(pid: int = typer.Option(None, help="product id, e.g. 0xD7", parser=lambda s: int(s, 0))):
    """The keyboard's keys: slot, label, default code, current override."""
    pid = pid or config_interface(None)["product_id"]
    layout, saved = load_layout(pid), load_state(pid)
    alias = {slot: name for name, slot in side_keys(layout).items()}
    for k in sorted(layout, key=lambda k: (k["y"] // 30, k["x"])):
        cur = saved.get(k["slot"])
        print(f"{alias.get(k['slot'], ''):3s} slot {k['slot']:3d}  {k['label']:10s} default {k['default']:#08x}"
              + (f"  -> {cur:#08x}" if cur is not None else ""))


@app.command("map")
def map_keys(
    specs: list[str] = typer.Argument(..., help="KEY=TARGET, e.g. m1=f13 m2=cmd+c slot:7=esc"),
    pid: int = typer.Option(None, parser=lambda s: int(s, 0)),
    write: bool = typer.Option(False, "--write", help="actually send to the keyboard"),
):
    """Remap keys. Without --write, print what would be sent and change nothing."""
    pid = pid or config_interface(None)["product_id"]
    layout = load_layout(pid)
    names = side_keys(layout) | {k["label"].lower(): k["slot"] for k in layout}
    slots = {k["slot"] for k in layout}
    overrides = load_state(pid)
    for spec in specs:
        key, _, target = spec.partition("=")
        key = key.lower()
        slot = int(key[5:]) if key.startswith("slot:") else names.get(key)
        if slot not in slots:
            raise typer.BadParameter(f"unknown key {key!r} (see `rkkb keys`)")
        overrides[slot] = parse_target(target)
        print(f"{key} (slot {slot}) -> {overrides[slot]:#08x}")
    send(pid, layout, overrides, write)


@app.command()
def reset(pid: int = typer.Option(None, parser=lambda s: int(s, 0)),
          write: bool = typer.Option(False, "--write")):
    """Restore RK's default keymap and forget saved overrides."""
    pid = pid or config_interface(None)["product_id"]
    send(pid, load_layout(pid), {}, write)


def send(pid: int, layout: list[dict], overrides: dict[int, int], write: bool):
    buffers = encode(layout, overrides)
    if not write:
        for b in buffers:
            print(b.hex(" "))
        print("dry run: nothing sent. Add --write to send.")
        return
    import hid
    dev = hid.device()
    dev.open_path(config_interface(pid)["path"])
    try:
        for b in buffers:
            if dev.send_feature_report(b) != len(b):
                raise typer.Exit(f"short write: {dev.error()}")
    finally:
        dev.close()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(pid).write_text(json.dumps({str(k): v for k, v in overrides.items()}, indent=1))
    print(f"sent {len(buffers)} reports; saved overrides to {state_path(pid)}")


if __name__ == "__main__":
    app()

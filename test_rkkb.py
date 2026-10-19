"""Check rkkb's encoder against USB captures of RK's own software (Kludge Knight docs/captures_s70.txt)."""
from pathlib import Path

import rkkb

CAPTURES = rkkb.kk_file("docs/captures_s70.txt").decode().splitlines()


def capture_block(after: str) -> list[bytes]:
    i = next(n for n, line in enumerate(CAPTURES) if after in line)
    rows = [l.strip() for l in CAPTURES[i:] if l.strip().startswith("0a09")]
    return [bytes.fromhex(r) for r in rows[:9]]


def test_default_keymap_matches_rk_software():
    got = rkkb.encode(rkkb.load_layout(0xD7), {})
    want = capture_block("reeset keyboard data")
    for i, w in enumerate(want):
        assert got[i][: len(w)] == w, f"report {i + 1} differs:\n got {got[i].hex()}\nwant {w.hex()}"


def test_macro_keys_as_media_match_rk_software():
    layout = rkkb.load_layout(0xD7)
    m = rkkb.side_keys(layout)
    media = {m["m1"]: 0x010000E9, m["m2"]: 0x010000EA, m["m3"]: 0x010000E2,
             m["m4"]: 0x0100006F, m["m5"]: 0x01000070,
             9: 0x010000}  # Caps Lock was also mapped to Ctrl when this capture was taken
    got = rkkb.encode(layout, media)
    want = capture_block("set macro keys to")
    for i, w in enumerate(want):
        assert got[i][: len(w)] == w, f"report {i + 1} differs:\n got {got[i].hex()}\nwant {w.hex()}"


def test_side_keys_are_slots_1_to_5():
    assert rkkb.side_keys(rkkb.load_layout(0xD7)) == {"m1": 1, "m2": 2, "m3": 3, "m4": 4, "m5": 5}


def test_targets():
    assert rkkb.parse_target("f13") == 0x6800
    assert rkkb.parse_target("cmd+c") == 0x080600
    assert rkkb.parse_target("ctrl+a") == 0x010400  # the S70's factory M1


def test_right_modifiers_and_modifier_only_targets():
    assert rkkb.parse_target("rctrl+pagedown") == 0x104E00
    assert rkkb.parse_target("rcmd+ropt") == 0xC00000
    assert rkkb.parse_target("shift") == 0x020000  # the S70's own LShift code


def test_igor_mac_config_has_one_esc():
    import tomllib
    cfg = tomllib.loads((Path(__file__).parent / "configs/igor-mac.toml").read_text())
    got = rkkb.resolve(rkkb.load_layout(0xD7), cfg.items())
    assert got[1] == 0x2900 and got[7] == 0x3500  # Esc on M1, the old Esc key sends `

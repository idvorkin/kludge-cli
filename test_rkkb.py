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


def test_describe_inverts_parse_target():
    for spec in ["f13", "cmd+c", "rctrl+pagedown", "ropt+rcmd", "opt", "esc"]:
        assert rkkb.describe(rkkb.parse_target(spec)) == spec
    assert rkkb.describe(0x010000E9) == "0x10000e9"  # media keys stay raw


def test_report_code_reads_boot_reports():
    assert rkkb.report_code([0x08, 0, 0, 0, 0, 0, 0, 0]) == 0x080000  # Win alone
    assert rkkb.report_code([0x10, 0, 0x4E, 0, 0, 0, 0, 0]) == 0x104E00  # rctrl+pagedown
    assert rkkb.report_code([0x01, 0x04, 0, 0x29, 0, 0, 0, 0, 0]) == 0x042900  # opt+esc, with a report id
    assert rkkb.report_code([0, 0, 0, 0, 0, 0, 0, 0]) == 0


def test_slots_for_code_follows_overrides():
    layout = rkkb.load_layout(0xD7)
    assert rkkb.slots_for_code(layout, {}, 0x080000) == [17]  # LWin
    assert rkkb.slots_for_code(layout, {17: 0x040000}, 0x080000) == []
    assert 17 in rkkb.slots_for_code(layout, {17: 0x040000}, 0x040000)


def test_igor_mac_config_has_one_esc():
    import tomllib
    cfg = tomllib.loads((Path(__file__).parent / "configs/igor-mac.toml").read_text())
    got = rkkb.resolve(rkkb.load_layout(0xD7), cfg.items())
    assert got[1] == 0x2900 and got[7] == 0x3500  # Esc on M1, the old Esc key sends `


def run_learn(monkeypatch, saved, codes, answers):
    """Drive `rkkb learn` with fake key presses and typed answers; returns the prompts shown."""
    import contextlib

    asked = []
    answers = iter(answers)
    monkeypatch.setattr(rkkb, "load_state", lambda pid: dict(saved))
    monkeypatch.setattr(rkkb, "keyboard_input", contextlib.contextmanager(lambda pid: (yield iter(codes).__next__)))
    monkeypatch.setattr(rkkb, "prompt", lambda text: asked.append(text) or next(answers))
    monkeypatch.setattr(rkkb, "send", lambda *a, **k: None)
    rkkb.learn(pid=0xD7)
    return asked


def test_learn_asks_which_key_when_two_send_the_same_code(monkeypatch):
    esc = rkkb.slots_for_code(rkkb.load_layout(0xD7), {}, 0x2900)[0]  # the Esc key itself
    asked = run_learn(monkeypatch, {1: 0x2900}, [0x2900, 0x2900], ["esc", "", "m1", "done"])
    assert "which key?" in asked[0] and "m1" in asked[0] and "esc" in asked[0]
    assert f"(slot {esc})" in asked[1]  # Esc picked, not the first match (M1)
    assert "(slot 1)" in asked[3]


def test_learn_skips_a_shared_code_on_enter(monkeypatch):
    asked = run_learn(monkeypatch, {1: 0x2900}, [0x2900, 0x080000], ["", "done"])
    assert "which key?" in asked[0]
    assert "(slot 17)" in asked[1]  # the next key press, nothing staged for the shared one


def test_no_terminal_signals_clears_isig_and_restores(monkeypatch):
    import termios

    calls = []
    attrs = [termios.IXON | termios.ICRNL, 0, 0, termios.ISIG | termios.ECHO, 0, 0, []]
    monkeypatch.setattr(rkkb.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: list(attrs))
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, a: calls.append((a[0], a[3])))
    try:
        with rkkb.no_terminal_signals():
            raise KeyError("interrupted mid-capture")
    except KeyError:
        pass
    off = (termios.ICRNL, termios.ECHO)
    assert calls == [off, (termios.IXON | termios.ICRNL, termios.ISIG | termios.ECHO)]  # restored after


def test_learn_tells_two_same_named_keys_apart_by_slot(monkeypatch):
    left, right = rkkb.slots_for_code(rkkb.load_layout(0xD7), {}, 0x2C00)  # the S70's two space keys
    asked = run_learn(monkeypatch, {}, [0x2C00], [str(right), "done"])
    assert f"space (slot {left}), space (slot {right})" in asked[0]
    assert f"(slot {right})" in asked[1]

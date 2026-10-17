# kludge-cli

Remap keys on a Royal Kludge (RK) keyboard from the command line. No browser, no Windows VM.

RK's configuration software only runs on Windows. [Kludge Knight](https://github.com/vinc3m1/kludgeknight)
reverse-engineered the remap protocol and does it in Chrome over WebHID. `kludge-cli` is a small Python port of
Kludge Knight's remap path, so you can script it: `rkkb map m1=esc --write`.

## Status

- **Tested on one keyboard:** the RK SPLIT70 three-mode (RK-S70 split, USB product ID `0x00D7`), on macOS.
- **Byte-verified:** the encoder reproduces USB captures of RK's own Windows software writing to an S70, in
  both the factory keymap and the macro keys set to media keys (`test_rkkb.py`).
- Other RK models with a Kludge Knight layout should work in principle, but they are untested. Try a dry run
  first, and keep `rkkb reset --write` handy.
- **Remapping only.** No macros (RK's macro protocol hasn't been reverse-engineered) and no lighting.

## Install

```bash
uv tool install git+https://github.com/idvorkin/kludge-cli
```

## Use

Connect the keyboard **by USB cable**. If it has a mode switch, set it to wired. Bluetooth and 2.4 GHz
receivers don't expose the remap interface.

```bash
rkkb list                      # RK keyboards with the remap interface
rkkb keys                      # every key: slot, label, factory code, your override
rkkb map m1=esc m2=f13         # dry run: print the 9 reports, send nothing
rkkb map m1=esc m2=f13 --write # send them
rkkb reset --write             # factory keymap
```

Keys are named by their label in RK's layout (`esc`, `a`, `capslock`, …), by `slot:N`, or, on keyboards with a
macro column, `m1`…`m5` (the leftmost column, top to bottom).

Targets:

| Form | Example | Notes |
|---|---|---|
| a key | `esc`, `f13`, `pagedown` | F13–F24 are handy for binding in other tools |
| modifiers + key | `cmd+c`, `rctrl+pagedown` | `ctrl shift alt/opt cmd/win`, and right-side `rctrl rshift ralt/ropt rcmd/rwin` |
| modifiers alone | `rcmd+ropt` | held for as long as the key is held: good for push-to-talk |
| raw firmware code | `0x6800` | see Kludge Knight's notes on the encoding |

In the keyboard's Mac mode (Fn+S on the S70), Win is sent as ⌘ and Alt as ⌥.

**The firmware can't be read, only written.** Every write sends the whole keymap: RK's defaults plus your
overrides, which are remembered in `~/.config/rkkb/<PID>.json`. Changes made with another tool get
overwritten by the next write.

## macOS notes

- **Input Monitoring.** Opening a keyboard needs Input Monitoring permission for the terminal app running
  `rkkb` (System Settings → Privacy & Security → Input Monitoring). An app that was updated while it was running
  must be restarted before the permission applies to it.
- **Karabiner-Elements** holds keyboards exclusively. `rkkb` tells Karabiner to skip the keyboard for the few
  seconds of a write, then restores `~/.config/karabiner/karabiner.json` byte for byte.

## Where the data comes from

Keyboard layouts are RK's own `KB.ini` files as Kludge Knight ships them, fetched from its GitHub at a pinned
commit and cached in `~/.cache/kludge-cli/`. To use a local checkout instead, set `KLUDGEKNIGHT_DIR`.

## License and credits

GPL-3.0-or-later. The buffer encoding is ported from Kludge Knight's `BufferCodec.ts`, which is itself derived
from [Rangoli](https://github.com/rnayabed/rangoli) by Debayan Sutradhar. Firmware codes, layouts and the S70
captures used in the tests come from Kludge Knight.

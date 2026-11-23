---
name: adding-fans
description: "Adds, replaces or removes a ceiling fan of an already-supported family (Mainstays 42-inch Hugger, Artika REM-ARTC-3) in the fan-esphome firmware: reads the remote's address with an RTL-SDR, adds the YAML package and a local name, validates, flashes and checks it. Use when asked to add another fan or remote of a supported model to fan-esphome. For an unknown brand or protocol, use investigating-fan-remotes instead."
---

# Adding a supported-family fan

## Rules

- Room names and credentials go only in the git-ignored `fan-names.yaml` / `secrets.yaml`. Committed files get neutral placeholders such as `Fan 4`.
- Get the owner's go-ahead before flashing or transmitting. The owner must be present to watch the fan. Never run unattended code scans or motor/timer tests.
- Leave existing fan numbers, addresses and button names unchanged: they set the Home Assistant entity identities. Do not change repo visibility.
- Leave the timing alone. The Mainstays receiver validates the 8444 µs sync gap; a gap of about 10.3 ms broke some buttons.
- Record what was RF-matched and what was human-confirmed in `docs/PROTOCOLS.md`. A predicted code is not a verified code.

## Setup

- Build: `python -m venv .venv`, then `.venv\Scripts\python -m pip install -r requirements.txt`.
- Capture: `pip install -r tools/requirements.txt`, an RTL-SDR, and `rtl_sdr` on PATH or in `RTL_SDR_EXE`. Per-OS steps are in README "Optional tool setup".
- Use PowerShell on Windows; ESP-IDF builds fail under Git Bash.

## Mainstays (32-bit, address per remote)

1. Run `python tools/rf_capture.py record fanN_any --seconds 6` and press any button about 2 s after it starts.
2. Check the modal code:
   - It has 32 bits.
   - Bits 16–19 are `0101`.
   - All eight nibbles XOR to 0.
   - The address is bits 0–15 as hex, such as `0x548D`.
3. Add one line under `packages:` in `fan-esphome.yaml`, using the next unused `n`:
   `  fanN: !include { file: fan.yaml, vars: { n: "N", fan_name: "${fanN_name}", addr: "0xABCD" } }`
4. Add `fanN_name: "Fan N"` to `fan-names.example.yaml`, and the real name to the local `fan-names.yaml`.
5. To remove a fan, delete its package line and both name entries. Tell the owner to delete its stale entities in Home Assistant, but not the shared ESPHome device.

## Artika (24-bit fixed codes)

- `artika.yaml` hard-codes one remote: address `0x5623` plus 8-bit commands.
- For a different Artika remote, capture every button with `rf_capture.py`. Replace only the address bytes, after checking that the command bytes match the table in `docs/PROTOCOLS.md`.
- Two Artika fans in one firmware need `artika.yaml` parameterised the way `fan.yaml` is, with unique script ids and name prefixes. That is a firmware change, so propose it to the owner first.
- The manual's pairing procedure could pair a receiver to the existing codes: power off for at least 15 s, power on, then press LIGHT + WARM within 10 s. This is untested.

## Validate, flash, verify

1. Run `.venv\Scripts\esphome config fan-esphome.yaml`, then `compile`.
2. Flash with `run --device COMx` (USB) or plain `run` (OTA). Flash only with approval.
3. With the owner watching, press a light button in Home Assistant, then one fan speed.
4. Optional SDR check, Mainstays only: `python tools/rf_bench.py --button "Fan N RF Speed 1" --expect <bits> --mic "<mic>"`. Compute the expected bits with:
   `python -c "a,c=0x548D,0x01;f=a<<16|0x5000|c<<4;x=0;exec('for s in range(4,32,4): x^=(f>>s)&15');print(format(f|x,'032b'))"`

## Gotchas

- Light buttons never beep; judge them by the light. A beep confirms a fan command arrived, not which speed.
- Reverse only acts while the fan is stopped. Brighter or dimmer at its limit looks dead.
- `rf_bench.py` decodes only 32-bit Mainstays frames. Use `rf_capture.py analyze <file.cu8>` for Artika.
- `rtl_sdr` needs about 2 s to start, and the dongle allows only one user at a time (close SDR#).
- If a fan doesn't respond but the SDR shows matching frames, move the bridge closer before suspecting the code.

---
name: adding-fans
description: "Adds, replaces or removes a ceiling fan of an already-supported family (Mainstays 42-inch Hugger, Artika REM-ARTC-3) in the fan-esphome firmware: reads the remote's address with an RTL-SDR, adds the YAML package and a local name, validates, flashes and checks it. Use when asked to add another fan or remote of a supported model to fan-esphome. For an unknown brand or protocol, use investigating-fan-remotes instead."
---

# Adding a supported-family fan

## Rules

- Put room names and credentials only in the git-ignored `fan-names.yaml` and `secrets.yaml`; use neutral placeholders like `Fan 4` in committed files.
- Don't flash or transmit without the user's go-ahead; they need to be watching the fan. Never run unattended code scans or motor/timer tests.
- Leave existing fan numbers, addresses, and button names alone; they set the Home Assistant entity identities. Don't change repo visibility.
- Don't touch the timing. The Mainstays receiver validates the 8444 µs sync gap; a gap around 10.3 ms broke some buttons.
- Note in `docs/PROTOCOLS.md` what was RF-matched versus human-confirmed. A predicted code doesn't count as verified.

## Setup

- To build, run `python -m venv .venv`, then `.venv\Scripts\python -m pip install -r requirements.txt`.
- Capture needs `pip install -r tools/requirements.txt`, an RTL-SDR, and `rtl_sdr` on PATH or in `RTL_SDR_EXE`; see README "Optional tool setup" for per-OS steps.
- Use PowerShell on Windows; ESP-IDF builds fail in Git Bash.

## Mainstays (32-bit, address per remote)

1. Run `python tools/rf_capture.py record fanN_any --seconds 6` and have the user press any button about 2 s after it starts.
2. Check the modal code:
   - It's 32 bits long.
   - Bits 16–19 are `0101`.
   - All eight nibbles XOR to 0.
   - Bits 0–15 are the hex address, such as `0x548D`.
3. Under `packages:` in `fan-esphome.yaml`, add a line with the next unused `n`: `  fanN: !include { file: fan.yaml, vars: { n: "N", fan_name: "${fanN_name}", addr: "0xABCD" } }`
4. Put `fanN_name: "Fan N"` in `fan-names.example.yaml` and the real name in local `fan-names.yaml`.
5. To remove a fan, delete its package line and both name entries, then tell the user to clear its stale Home Assistant entities (not the shared ESPHome device).

## Artika (24-bit fixed codes)

- `artika.yaml` hard-codes one remote: address `0x5623` and 8-bit commands.
- For another Artika remote, capture every button with `rf_capture.py`, confirm the command bytes match the table in `docs/PROTOCOLS.md`, then replace only the address bytes.
- Supporting two Artika fans in one firmware means parameterizing `artika.yaml` like `fan.yaml`, with unique script ids and name prefixes. Propose that firmware change to the user first.
- The manual's pairing sequence might bind a receiver to the existing codes: power off for at least 15 s, power on, then press LIGHT + WARM within 10 s (untested).

## Validate, flash, verify

1. Validate with `.venv\Scripts\esphome config fan-esphome.yaml`, then run `compile`.
2. After the user approves, flash with `run --device COMx` (USB) or `run` (OTA).
3. With the user watching, press a light button in Home Assistant first, then one fan speed.
4. Optional SDR check (Mainstays only): run `python tools/rf_bench.py --button "Fan N RF Speed 1" --expect <bits> --mic "<mic>"`, computing the expected bits with `python -c "a,c=0x548D,0x01;f=a<<16|0x5000|c<<4;x=0;exec('for s in range(4,32,4): x^=(f>>s)&15');print(format(f|x,'032b'))"`.

## Gotchas

- Light buttons never beep, so watch the light. A beep only confirms a fan command arrived, not which speed.
- Reverse only works while the fan is stopped. Brighter or dimmer looks dead at its limit.
- `rf_bench.py` only decodes 32-bit Mainstays frames; use `rf_capture.py analyze <file.cu8>` for Artika.
- `rtl_sdr` takes about 2 s to start; only one program can use the dongle at once (close SDR#).
- If the SDR sees matching frames but the fan doesn't respond, move the bridge closer before blaming the code.

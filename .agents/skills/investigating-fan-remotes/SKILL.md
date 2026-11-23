---
name: investigating-fan-remotes
description: "Investigates a new 433 MHz ceiling-fan remote for fan-esphome: identifies it from its FCC ID, captures and decodes every button with an RTL-SDR, adds a separate firmware package, and plans a supervised replay. Use when asked to support a new fan brand or remote, decode an RF remote, or find out why a replay is not received. For another fan of an already-supported model, use adding-fans."
---

# Investigating a new fan remote

## Rules

- Only the RTL-SDR, `rtl_sdr` and numpy are required (`tools/rf_capture.py`). The microphone and camera (`tools/rf_bench.py`) are optional evidence.
- Label every claim as one of:
  - **capture**: the original remote, recorded by the SDR;
  - **prediction**: computed from the protocol model;
  - **RF replay**: the bridge's transmission, recorded by the SDR;
  - **human confirmation**: the user watched the fan respond.

  An RF match proves only that the code was sent.
- Transmit only with the user present and ready, one command at a time. Never scan or guess codes unattended, and never leave motors or timers running untested.
- Keep raw `.cu8` files, audio and room camera frames in the git-ignored `runs/`. Commit only cropped or derived images, and neutral names.

## Steps

1. **Identify the remote.** Look up the FCC ID on the label at fccid.io. The test report gives frequency, modulation and pulse widths; the manual gives toggle vs discrete buttons, timers and pairing.
2. **Capture.**
   - Run `python tools/rf_capture.py record <name> --seconds 120`.
   - The user presses every button once, in a stated order, and reports what each did.
   - Then press one button twice, to tell fixed codes from rolling codes.
3. **Decode.** Run `python tools/rf_capture.py analyze runs/captures/<name>.cu8 --plot runs/captures/<name>.png`.
   - The histograms must show two HIGH widths (PWM). Otherwise the printed bits are meaningless; decode by hand.
   - Note the frame length, frames per press, sync gap, and modal HIGH/LOW durations.
   - Split the address from the command, and look for a checksum. Write findings to `docs/PROTOCOLS.md`.
4. **Implement.** Add a new package file modelled on `artika.yaml`:
   - its own queued script that builds one blocking `remote_transmitter.transmit_raw` waveform on the shared `rf_tx`;
   - the measured median timings and frame count;
   - stateless buttons for toggles.

   Add a stateful fan or light entity only for confirmed discrete commands. Include the package in `fan-esphome.yaml`, then run `esphome config` and `compile`.
5. **Replay, supervised.**
   - Get approval, then flash.
   - Test the light first: record the press with `rf_capture.py record` while the user presses the button in Home Assistant.
   - Compare the bits and timing against the capture, and ask the user what the fan did.
   - Then try one speed and power, then the rest, one at a time.

## When a replay is not received

- Check placement first. The Artika replay failed until the bridge was moved closer; then every control worked.
- A carrier offset is a hypothesis until proven. At gain 40 the ADC clips, which distorts frequency estimates, so re-record the remote and replay back to back at `--gain 10`–`20`.
- Change timing only with evidence from the capture. Mainstays receivers validate the sync gap.

## Gotchas

- Use 1 MS/s. 250 kHz cannot resolve pulses of about 300 µs.
- The last frame of a press ends in silence, not at a gap; a parser that waits for a closing edge drops it.
- `rtl_sdr` needs about 2 s before samples flow, and only one program can use the dongle at a time.
- A beep confirms a command was accepted, not its meaning. Light commands may not beep.

---
name: investigating-fan-remotes
description: "Investigates a new 433 MHz ceiling-fan remote for fan-esphome: identifies it from its FCC ID, captures and decodes every button with an RTL-SDR, adds a separate firmware package, and plans a supervised replay. Use when asked to support a new fan brand or remote, decode an RF remote, or find out why a replay is not received. For another fan of an already-supported model, use adding-fans."
---

# Investigating a new fan remote

## Rules

- You only need an RTL-SDR, `rtl_sdr`, and numpy (`tools/rf_capture.py`). The microphone and camera (`tools/rf_bench.py`) are optional evidence.
- Label every claim as one of:
  - **capture**: the original remote, recorded with the SDR.
  - **prediction**: computed from the protocol model.
  - **RF replay**: the bridge's transmission, recorded with the SDR.
  - **human confirmation**: the user watched the fan respond.

  An RF match only proves the code was sent.
- Only transmit when the user is present and ready, one command at a time. Never scan or guess codes unattended, or leave motors or timers running untested.
- Keep raw `.cu8` files, audio, and room camera frames in the git-ignored `runs/`. Commit only cropped or derived images, and use neutral names.

## Steps

1. **Identify the remote.** Look up the label's FCC ID on fccid.io. The test report gives frequency, modulation, and pulse widths; the manual covers toggle vs discrete buttons, timers, and pairing.
2. **Capture.**
   - Run `python tools/rf_capture.py record <name> --seconds 120`.
   - Have the user press each button once in a stated order and report what it did.
   - Then have them press one button twice to tell fixed from rolling codes.
3. **Decode.** Run `python tools/rf_capture.py analyze runs/captures/<name>.cu8 --plot runs/captures/<name>.png`.
   - Check that the histograms show two HIGH widths (PWM); if not, ignore the printed bits and decode by hand.
   - Record the frame length, frames per press, sync gap, and modal HIGH/LOW durations.
   - Separate the address and command, look for a checksum, and log findings in `docs/PROTOCOLS.md`.
4. **Implement.** Create a new package file modeled on `artika.yaml` with:
   - its own queued script building one blocking `remote_transmitter.transmit_raw` waveform on the shared `rf_tx`;
   - the measured median timings and frame count;
   - stateless buttons for toggles.

   Only add a stateful fan or light entity for confirmed discrete commands. Include the package in `fan-esphome.yaml`, then run `esphome config` and `compile`.
5. **Supervised replay.**
   - Get the user's approval, then flash.
   - Test the light first, recording with `rf_capture.py record` while the user presses the button in Home Assistant.
   - Compare the bits and timing against the capture, then ask the user what the fan did.
   - Next, test one speed and power, then the rest one at a time.

## When a replay is not received

- Check placement first: the Artika replay failed until the bridge was moved closer, and then every control worked.
- Treat a carrier offset as a hypothesis until proven. Gain 40 clips the ADC and skews frequency estimates, so re-record the remote and replay back to back at `--gain 10`–`20`.
- Only change timing with evidence from the capture; Mainstays receivers validate the sync gap.

## Gotchas

- Use 1 MS/s; 250 kHz can't resolve pulses of about 300 µs.
- The final frame of a press ends in silence, not a gap, so a parser waiting for a closing edge drops it.
- `rtl_sdr` takes about 2 s before samples flow; only one program can use the dongle at once.
- A beep only confirms a command was accepted, not its meaning; light commands may not beep.

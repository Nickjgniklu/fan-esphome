# fan-esphome

ESPHome firmware that controls 433.92 MHz RF ceiling fans and their lights from
Home Assistant over WiFi, using the ESPHome native API. It runs on a Seeed XIAO
ESP32-C6 with an OOK transmitter module on **D10 (GPIO18)**.

For each fan, Home Assistant gets:

- a fan entity (speeds 1–6, off, direction)
- a light entity (on/off)
- one button per remote code, including light brighter, dimmer, and color

RF is one-way, so the fan and light states are assumed. If someone uses the
physical remote, use the buttons to bring things back in line.

## Supported fan

All the fans this controls are the same model: the
[Mainstays 42 in. Hugger Ceiling Fan with LED Light and Remote Control](https://www.walmart.com/ip/Mainstays-42-in-Hugger-Ceiling-Fan-with-LED-Light-Remote-Control-6-Speeds-Reverse-Airflow-Black-Walnut-Blades/19292811884)
(Black/Walnut blades). The product page lists:

- model FSI 90-4201H-4B
- hugger (flush) mount, 4 blades, DC motor
- 6 speeds, reverse airflow
- one integrated LED light

What fan_control found about its remote:

- 433.92 MHz OOK remote. Buttons: 6 speeds, off, reverse, and light toggle,
  brightness up/down, and color cycle.
- Each remote has its own 16-bit address. There is no pairing mode, so this
  device sends each fan's codes with that fan's remote address.
- Fan commands beep; light commands don't.
- Direction only changes while the fan is stopped.

## Files

| File | Contents |
|---|---|
| `fan-esphome.yaml` | Device, WiFi, transmitter, timing, command codes, and the list of fans |
| `fan.yaml` | Package for one fan, included once per fan with its address |
| `secrets.example.yaml` | Template for `secrets.yaml` (git-ignored) |

## Build and flash

Run these from PowerShell. ESP-IDF builds fail under Git Bash.

```powershell
copy secrets.example.yaml secrets.yaml   # then fill it in
python -m esphome config fan-esphome.yaml
python -m esphome run fan-esphome.yaml --device COM5   # first flash over USB
python -m esphome run fan-esphome.yaml                 # later, over the air
python -m esphome logs fan-esphome.yaml                # each press logs "RF TX <bits>"
```

## Adding a fan

Take any code captured from the new fan's remote; its first 16 bits are the
address. Then add one line under `packages:` in `fan-esphome.yaml`:

```yaml
  fan3: !include { file: fan.yaml, vars: { n: "3", fan_name: "Fan 3", addr: "<16 bits>" } }
```

This works when the remote is the same model: bits 16–21 are `010100`, and its
buttons use the same 10-bit commands as fan 1. If a different model's commands
differ, it needs its own command set.

## Protocol

The protocol was reverse-engineered with an RTL-SDR in the `fan_control`
project (`docs/PROTOCOL.md`, `data/*.sig`). Every fan 1 code below was replayed
from an ESP32 and confirmed on the real fan.

- OOK at 433.92 MHz. Each frame is 32 bits, sent MSB first with no lead pulse:
  - bit `1`: 768 µs high, then 274 µs low
  - bit `0`: 274 µs high, then 768 µs low
  - after the last bit: a 274 µs trailing high, then **8444 µs low**
- Each press sends 10 frames back to back.
- **The receiver validates the 8444 µs sync gap.** A ~10.3 ms gap made some
  buttons silently fail.
- Frame layout:

  | Bits | Field |
  |---|---|
  | 0–15 | Address of the remote and fan |
  | 16–21 | Model constant `010100` |
  | 22–31 | Command |

- Every valid frame has even parity, so an odd-parity capture is probably a
  mis-capture.

| Button | Command (bits 22–31) |
|---|---|
| speed1 | `0000010101` |
| speed2 | `0010011101` |
| speed3 | `0001110011` |
| speed4 | `0010001100` |
| speed5 | `0001000000` |
| speed6 | `0001010001` |
| fan off | `0000100110` |
| reverse direction | `1000100100` |
| light toggle | `0010111111` |
| light color cycle | `0011011001` |
| light brighter | `1101010010` |
| light dimmer | `1101000011` |

| Fan | Address | Status |
|---|---|---|
| Fan 1 | `1000011001111000` | All 12 buttons captured and verified |
| Fan 2 | `1111111110001001` | Only speed1 captured (same command as fan 1); the rest assume fan 1's commands |

### Testing notes

- Only fan commands beep; judge the light buttons by the light itself.
- Reverse was verified with the fan stopped.
- Test "brighter" from a dim light and "dimmer" from a bright one. At the
  limit, a working button looks dead.

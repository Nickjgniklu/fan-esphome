# fan-esphome

ESPHome firmware that controls 433.92 MHz RF ceiling fans and their lights from
Home Assistant over WiFi, using the ESPHome native API. It runs on a Seeed XIAO
ESP32-C6 with an OOK transmitter module on **D10 (GPIO18)**.

For each fan, Home Assistant gets:

- a fan entity (speeds 1–6, off, direction)
- two stateless buttons, `<Fan> Light On` and `<Fan> Light Off`
- raw fan buttons and light brighter, dimmer, and color buttons

**Light On and Light Off are intent labels, not discrete RF on/off commands.**
For now, BOTH send the known light-toggle code on every press. Either button
can turn an already-on light off or an already-off light on. Repeated presses
are never deduplicated. There is no assumed light state, stateful light entity,
or redundant raw light-toggle button. This avoids suppressing a press because
Home Assistant thinks the light is already in the requested state; it does not
provide guaranteed on/off behavior. Genuine discrete commands remain under research.

RF is one-way, so the fan entity's state is still assumed. Raw fan buttons do
not update it. Existing HA automations using `light.turn_on`/`light.turn_off`
must be changed to `button.press` on the replacement entities. Home Assistant
may retain the removed light/raw-toggle entities as unavailable until you
remove those obsolete entries from its entity registry.

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

Generate the API encryption key with `openssl rand -base64 32`. The example
contains placeholders only; never use it unchanged or commit real credentials.

## Adding a fan

Capture any button from a remote of this model and take its first 16 bits as
the address. The firmware computes the checksum using the model below; no
separate key is configured. Uncaptured buttons assume the shared button bytes.

Then add one line under `packages:` in `fan-esphome.yaml`:

```yaml
  fan3: !include { file: fan.yaml, vars: { n: "3", fan_name: "Fan 3", addr: "0x548D" } }
```

Use a unique `n` and display name for each fan.

To check a button over the air, `tools/rf_bench.py` presses it through the API
while it records the RTL-SDR, the PC microphone and a snapshot camera on one
clock. It decodes every frame and reports any beep and changes in the picture.

```powershell
python -m pip install -r tools/requirements.txt
python tools/rf_bench.py --button "Fan 3 RF Speed 1" --expect 01010100100011010101000000010000 --mic "YOUR_MIC_NAME"
python tools/rf_bench.py --remote --seconds 120 --video --mic "YOUR_MIC_NAME"
```

The bench uses an RTL-SDR at 433.92 MHz and 1 MS/s, with the bridge at
`fan-esphome.local` and camera at `http://fan-cam.local:8080/`. Select a WASAPI
microphone with `--mic`; override hosts with CLI options. Put `rtl_sdr` on PATH
or set the local `RTL_SDR_EXE` environment variable to its executable path.
Runs are ignored by git and contain timestamped JPEG frames,
audio WAV, decoded RF frames, a summary and a shared-clock timeline. SDR timing
is estimated from USB chunk arrival; camera timestamps are HTTP request
midpoints, not sensor exposure times. Correlation is approximate, not a hardware
synchronized measurement. A beep is evidence of command acceptance, not proof
of the exact speed or direction; video must establish those separately.
With `--video`, FFmpeg exports `camera.mp4` paced by the recorded frame times.
It is silent; the separate WAV starts at `timing.audio_start_s`, and the video
starts at the first `timing.camera_frame_times_s` value in `summary.json`.

## Protocol

The protocol was reverse-engineered with an RTL-SDR in the `fan_control`
project (`docs/PROTOCOL.md`, `docs/CODE_PREDICTION.md`, real `data/*.sig` captures).
The generated fan3 files without `_capture` are not used. Every fan 1 code was replayed
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
  | 16–19 | Model nibble `0x5` |
  | 20–27 | Button byte |
  | 28–31 | XOR of the preceding seven nibbles |

- All eight nibbles XOR to zero under the best-supported compact model. All 16
  original captures from three remotes are consistent with it; even parity
  follows from it. This is not unique proof: a fixed fan-specific mask predicts
  identical codes for these remotes. The rule was discovered in these data, so
  the matching frames do not give a calibrated chance probability. A spot
  capture neither distinguishes those models nor verifies every button.

| Button | Byte (hex) |
|---|---|
| speed1 | `01` |
| speed2 | `09` |
| speed3 | `07` |
| speed4 | `08` |
| speed5 | `04` |
| speed6 | `05` |
| fan off | `02` |
| reverse direction | `22` |
| light toggle | `0B` |
| light color cycle | `0D` |
| light brighter | `35` |
| light dimmer | `34` |

| Fan | Address | Status |
|---|---|---|
| Fan 1 | `0x8678` | All 12 buttons captured and verified in fan_control |
| Fan 2 | `0xFF89` | Speed1 captured; remaining buttons checksum-generated, not physically verified here |
| Fan 3 | `0x548D` | Speeds 1–3 captured originally; local replay sweep exercised all 12 buttons |

For fan 3, a later real-remote reference also captured speed6, off and light
toggle. Every button in the replay sweep had at least nine SDR frames matching
its independently expected code. Speeds 1–6 beeped, light toggle changed off/on,
and dimmer/brighter changed the camera measurement in opposite directions.
Color and reverse were RF-matched but their exact color/rotation behavior is
not yet functionally verified. Beeps alone do not prove the requested speed.
The originally uncaptured nine buttons used fan 1's button bytes; they were
predictions, not real-remote captures. The generated non-capture fan3 `.sig`
files fail the inferred checksum, remain untested, and are never imported.

### Discrete light-command search (2026-11-20)

A bounded exploratory test on fan 3 (`0x548D`) looked for separate light-on and
light-off commands, rather than assuming adjacent command bytes had a meaning.
Each press used the inferred checksum and normal 10-frame timing.

| Candidate byte | Observed result |
|---|---|
| `0A` | No visible light-state change in two trials from ON and two from OFF; 7–10 matching SDR frames per trial, no detected beep |
| `0C` | First trial from ON left the light on, produced a beep, and started blade motion; 9 matching SDR frames. Exact fan function unknown |

The initial test stopped on that unexpected fan behavior. The known fan-off
command was sent afterward (10 matching frames). A later owner-authorized scan
completed `00`–`7F` from both light ON and OFF before being paused at the owner's
request to stop the beeping/flashing. Only `0B` changed the observed on/off
state; no discrete command was found. `80`–`FF` were not tested. This is a scan
under the inferred checksum model with a short observation window, not proof
that discrete commands cannot exist. RF matches confirm transmission, not the
receiver's interpretation. The scanner is stopped and its temporary controls
are removed from the normal firmware.

Local evidence is in the ignored `runs/discrete-light-results.json` and its
referenced per-trial recordings.
The partial sweep is in `runs/20261120_152943_full_light_scan/` (also ignored).

### Stateless light-button verification (2026-11-20)

The replacement firmware passed `esphome config`, compiled, and was flashed
over USB with written-data verification. The live encrypted native API exposed
all six Light On/Off buttons for the three fans, with no light entities,
raw-toggle buttons, or scanner controls.

On fan 3, consecutive presses of **On, On, Off, Off** each produced nine SDR
frames matching the known toggle code. Camera observations were **ON → OFF →
ON → OFF → ON**, with no detected beeps. Thus both names are repeatable,
stateless aliases for toggle, not idempotent light commands. Fan 1/2 entity
discovery was checked, but their replacement buttons were not physically
exercised in this test. Brightness/color buttons and fan controls are unchanged.

### Repository privacy

Real `secrets.yaml`, ESPHome build output, logs, Python caches, and local `runs/`
recordings are ignored and must stay local. `secrets.example.yaml` contains
placeholders only. The bench uses generic hostnames and an executable selected
through PATH or a local environment variable, not a personal machine path.
Configured RF addresses and documented protocol examples are deliberately
included; review those before any future public release. Repository visibility
must not be changed without separate owner approval.

### Normal button checks

- Only fan commands beep; judge the light buttons by the light itself.
- fan_control verified reverse on fan 1 with it stopped. The local fan 3 sweep
  received a beep but has not yet established the actual rotation direction.
- Test "brighter" from a dim light and "dimmer" from a bright one. At the
  limit, a working button looks dead.

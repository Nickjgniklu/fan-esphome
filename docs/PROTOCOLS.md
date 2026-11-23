# Protocol, verification and deployment notes

Reference detail moved out of the README quick start. Capture/verification terms used here: **capture** = recorded from the original remote; **prediction** = a code computed from the protocol model, not captured; **RF replay** = the ESP32 transmission recorded by the SDR; **human confirmation** = the owner watched the fan respond. RF matches confirm transmission, not that the receiver acted.

## Contents

- [Mainstays protocol](#mainstays-protocol)
- [Artika REM-ARTC-3](#artika-rem-artc-3-controls-owner-tested-nearby)
- [Bench recording details](#bench-recording-details)
- [Home Assistant migration notes](#home-assistant-migration-notes)

## Mainstays protocol

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
| Fan 1 (retired, not configured) | `0x8678` | Historical reference: all 12 buttons captured and verified in fan_control |
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

### Normal button checks

- Only fan commands beep; judge the light buttons by the light itself.
- fan_control verified reverse on fan 1 with it stopped. The local fan 3 sweep
  received a beep but has not yet established the actual rotation direction.
- Test "brighter" from a dim light and "dimmer" from a bright one. At the
  limit, a working button looks dead.

## Artika REM-ARTC-3 (controls owner-tested nearby)

This package is separate from Mainstays: no nibble checksum, no 32-bit frame,
and no reuse of Mainstays timing. It shares only the existing blocking OOK
transmitter on GPIO18. It exposes 13 buttons: Light On/Off intent aliases,
Fan Power Toggle, speeds 1–3, reverse, brightness up/down, cooler/warmer CCT,
and 1h/4h timers. There is deliberately **no stateful Artika fan entity or
discrete fan-off button**: captured fan power is treated as a toggle, and
the owner's general confirmation does not establish detailed speed-button
power semantics for a stateful fan entity. Both light
intent buttons send the same toggle; neither guarantees the requested state.

Evidence comes from the sibling `artika-fan-rf/FINDINGS.md` and
`captures/session1_all_buttons.cu8` (1 MS/s, 433.92 MHz), not copied into this
repo. Independent re-decoding of all 13 press windows recovered the same 66
frames and all listed codes. The apparent 25th HIGH pulse is sync, not data.
Only the cooler/warmer effects of the original remote were explicitly reported
by the owner; light-power toggle is supported by the manual, not an explicit
observation of those original presses. Button-to-code labels otherwise follow
the confirmed physical press order.

The EV1527 / rc-switch-protocol-1 **style** waveform is 24 bits MSB first plus
one sync HIGH/LOW pair. This is a waveform classification, not proof of an
encoder chip. The firmware uses these measured median durations:

| Symbol | HIGH (µs) | LOW (µs) |
|---|---:|---:|
| `0` | 410 | 1229 |
| `1` | 1218 | 421 |
| Sync after data | 410 | 12594 |

This is approximately T = 410 µs, 1:3 / 3:1 data and 1:31 sync. A frame is
52.340 ms. Each press sends **five total frames**, about 261.7 ms, in one
blocking RMT waveform. Captures show five frames for 12 presses and six for
the first light press. These timings/counts are capture-derived choices;
the nearby light test succeeded, but receiver tolerance remains unknown.

| Button | Captured 24-bit code |
|---|---|
| Light toggle (both intent buttons) | `0x562305` |
| Fan Power Toggle | `0x562330` |
| Speed 1 / 2 / 3 | `0x562333` / `0x56231A` / `0x562332` |
| Reverse | `0x56231B` |
| Brightness up / down | `0x562319` / `0x562335` |
| Timer 1h / 4h | `0x562316` / `0x562336` |
| Cooler / warmer CCT | `0x562318` / `0x562337` |

### Deployment and replay checks (2026-11-23)

`esphome config` and compilation passed. The combined firmware was flashed over
USB with written-data verification. Its encrypted WiFi native API exposes two
renamed Mainstays fan entities, their 26 companion buttons, and 13 Artika
buttons. Fan 1 and stateful light/probe entities are absent. Existing Mainstays
button keys are preserved; the Mainstays encoder is unchanged.

One Artika **Light On** press was sent while the owner reported light OFF and
motor RUNNING. **The owner reported that the light did not turn on.** No motor,
reverse, or timer commands followed. RF matching is not receiver acceptance.

Independent comparison of the saved replay IQ and both original light presses
found the same `0x562305`, MSB-first polarity, 24 data bits plus sync HIGH:

| On-air measurement | Original remote | ESP32 replay |
|---|---:|---:|
| Total frames | 6 first press; 5 last press | 5 |
| Zero HIGH / LOW medians | 409 / 1229–1230 µs | 424 / 1215 µs |
| One HIGH / LOW medians | 1217 / 421–422 µs | 1234 / 407 µs |
| Sync HIGH median | 409 µs | 425 µs |
| Inter-frame LOW gaps | 12585–12645 µs | 12581–12582 µs |
| Frame start cadence | 52305–52428 µs | 52376–52382 µs |

Both bursts start directly with data, without a separate leading HIGH. After
the final sync HIGH, the observed carrier stays low through the remaining
recording (at least 305 ms for the original snippets, 2.24 s for replay).
An initial four-frame result was a scratch parser omitting that final
silence-delimited frame; independent decoding and corrected reanalysis recover
all five. No extra transmission was needed to resolve it.

The strongest long-pulse spectral peak is near 433.913 MHz for the original
remote and 433.793 MHz for replay on the same nominally tuned SDR. **This is
only a carrier-mismatch hypothesis**, not an established failure cause or a
calibrated frequency measurement: both captures have ADC clipping, and replay
also has a strong mirrored spectral peak. A lower-gain comparison is needed
to distinguish transmitter frequency error from measurement artifacts. No
firmware timing change is justified by the failed light test alone.

The owner then unplugged/moved the bridge nearer and reported **"Yes it is
working"** in response to the supervised Home Assistant light test. This
confirms nearby Artika light operation and HA connectivity after relocation.
The same flashed firmware was used; no timing adjustment or second flash was
needed. This supports a range/placement explanation for the initial failure,
but does not isolate its exact RF cause or prove a carrier mismatch.

The owner subsequently reported **"I tested all the controls for it they all
work"**. All 13 exposed Artika buttons are therefore recorded as owner-tested
and working after relocation: light-intent aliases, fan power/speeds, reverse,
brightness, CCT and timer controls. This is human functional confirmation,
distinct from the automated API discovery and SDR light-waveform checks.
Detailed per-button observations and repeated-press sequences were not
recorded. In particular, the report does **not** establish that the 1h/4h
timers were observed through their full elapsed durations or that either
light-intent button is an idempotent on/off command.

Keep the selected external antenna attached and use stable USB power. No
PC/SDR connection is required for HA operation. RF evidence stays in ignored
`runs/` recordings. No further commands were sent after the first light test;
the successful nearby test was performed by the owner through HA.

### Verification limits

No more hardware tests are required for this delivery. Exact timer durations,
quantitative speed/direction measurements, repeated light-alias sequences and
calibrated carrier/range measurements remain outside the recorded evidence.
Any future live investigation must coordinate SDR/transmitter ownership and
obtain the owner's readiness before sending commands; do not resume hidden-code
scans or unattended motor/timer tests.

The existing `tools/rf_bench.py` decoder is Mainstays-specific (32 bits), not an
Artika verifier. Use `tools/rf_capture.py` (adapted from the Artika
investigation's level-preserving SDR analysis), which decodes any PWM OOK
frame length. Long presses, simultaneous-button/beeper combinations, and pairing
are not captured or implemented here. No genuine discrete light ON/OFF is known.


## Bench recording details

`tools/rf_bench.py` presses a button through the API (or records the real
remote) while it records the RTL-SDR, the PC microphone and a snapshot camera
on one clock. It decodes every Mainstays 32-bit frame and reports any beep and
changes in the picture. It requires a microphone; the camera is optional (no
frames are saved if the URL is unreachable).

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


## Home Assistant migration notes

`fan-names.yaml` contains `substitutions.fan2_name`, `substitutions.fan3_name`,
and `substitutions.artika_name`. The first two set Mainstays fan entity names;
the last sets the new Artika button-name prefix. Edit only that ignored file
for personal room names; keep them out of committed files. Copy the
neutral example on a fresh checkout before validating or compiling. Changing
the file takes effect only after rebuilding and flashing the firmware.

Fan numbers, RF addresses, and YAML fan IDs (`fan_2`, `fan_3`) stay fixed.
Companion button names deliberately remain `Fan 2 …` / `Fan 3 …`, so their
name-derived native API identities stay unchanged when room names change.
Brightness/color and stateless Light On/Off behavior are unchanged.
Artika has no previously deployed entities to preserve. Changing its button
prefix later changes name-derived API identities, so choose it before first
deployment and use HA-only friendly-name overrides for subsequent room renames.

**Fan entity names affect identity in this ESPHome version.** There is no
supported separate display-name/object-ID option, and keeping a YAML `id`
alone does not prevent a new Home Assistant registry entry after a rename.
Before flashing, record the existing two HA fan entity IDs and back up affected
automations. After discovery, retire/delete the old unavailable fan entries
and assign their exact former entity IDs to the new fan entries in HA entity
settings. Do not choose HA's option to regenerate IDs when only editing a
friendly name. Alternatively, keep the neutral names in the local file and
set friendly names directly in HA if no firmware-side rename is desired.

After the Fan 1 removal is flashed, its fan and 13 button entities may remain
in HA as unavailable. Remove Fan 1 references from dashboards/automations, then
delete only its stale entity-registry entries under Settings → Devices &
services → Entities. **Do not delete the shared ESPHome device/integration**:
Fan 2 and Fan 3 still use it. Earlier obsolete stateful light/raw-toggle entries
can also be removed after checking they are not referenced.


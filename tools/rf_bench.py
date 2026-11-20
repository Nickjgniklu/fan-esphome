"""Record one RF press with the SDR, PC microphone and fan camera on one clock.

    python tools/rf_bench.py --button "Fan 1 RF Speed 1"   # press via the ESPHome API
    python tools/rf_bench.py --remote --seconds 10          # you press the real remote

Every stream is timestamped with time.perf_counter() (seconds since the run
started), so the SDR frames, the beep and the camera frames line up with the
press. Each run writes runs/<time>_<label>/: summary.json, timeline.png,
before.jpg / after.jpg and every camera frame.

What it checks:
  SDR    decodes every 32-bit frame (bit 1 = HIGH > LOW), the pulse widths and
         sync gap, and compares the bits with what the device logged ("RF TX").
  mic    finds tone bursts (the fan's beep; fan commands only, lights never beep) by narrowband peak vs. background.
  camera saturated-pixel share before vs. after (the light) and frame-to-frame
         difference (blade motion).
Needs rtl_sdr.exe, sounddevice, aioesphomeapi, numpy, scipy, matplotlib, PIL.
Close SDR# and any other user of the dongle first.
"""

import argparse
import asyncio
import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
from PIL import Image
from scipy.ndimage import uniform_filter1d

ROOT = Path(__file__).resolve().parent.parent
RTL_SDR_EXE = os.environ.get("RTL_SDR_EXE", "rtl_sdr")
SDR_RATE = 1_000_000
AUDIO_RATE = 48_000
T0 = time.perf_counter()


def now():
    return time.perf_counter() - T0


# ── recorders ────────────────────────────────────────────────────────────────

class SdrRecorder:
    """Streams IQ from rtl_sdr.exe; stamps each chunk on arrival."""

    def __init__(self, freq_mhz, gain):
        self.cmd = [RTL_SDR_EXE, "-f", str(int(freq_mhz * 1e6)), "-s", str(SDR_RATE),
                    "-g", str(gain), "-"]
        self.chunks = []  # (arrival_time, bytes)

    def start(self):
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        while True:
            b = self.proc.stdout.read(1 << 16)
            if not b:
                return
            self.chunks.append((now(), b))

    def wait_ready(self, timeout=8.0):
        end = time.time() + timeout
        while not self.chunks and time.time() < end:
            time.sleep(0.05)
        return bool(self.chunks)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.thread.join(timeout=5)

    def envelope(self):
        """Returns (start_time, magnitude at 1 sample/us). The start time comes
        from the last chunk's arrival minus everything streamed before it."""
        raw = np.frombuffer(b"".join(c for _, c in self.chunks), dtype=np.uint8)
        raw = raw[: len(raw) // 2 * 2].astype(np.float32) - 127.5
        mag = np.hypot(raw[0::2], raw[1::2])
        t_end = self.chunks[-1][0]
        return t_end - len(mag) / SDR_RATE, uniform_filter1d(mag, 8)


class MicRecorder:
    def __init__(self, name_hint):
        self.device = None
        for i, d in enumerate(sd.query_devices()):
            api = sd.query_hostapis(d["hostapi"])["name"]
            if d["max_input_channels"] > 0 and name_hint.lower() in d["name"].lower() and "WASAPI" in api:
                self.device = i
        if self.device is None:
            raise SystemExit(f"No WASAPI microphone matching {name_hint!r}")
        self.blocks = []  # (adc_time, samples)

    def start(self):
        def cb(data, frames, t, status):
            offset = now() - self.stream.time  # stream clock -> our clock
            self.blocks.append((t.inputBufferAdcTime + offset, data[:, 0].copy()))
        self.stream = sd.InputStream(device=self.device, samplerate=AUDIO_RATE, channels=1,
                                     dtype="float32", callback=cb)
        self.stream.start()

    def stop(self):
        self.stream.stop()
        self.stream.close()

    def audio(self):
        if not self.blocks:
            return 0.0, np.zeros(0, np.float32)
        return self.blocks[0][0], np.concatenate([b for _, b in self.blocks])


class CamRecorder:
    def __init__(self, url):
        self.url = url
        self.frames = []  # (time_mid, jpeg bytes)
        self.running = False

    def _loop(self):
        while self.running:
            t1 = now()
            try:
                with urllib.request.urlopen(self.url, timeout=3) as r:
                    jpg = r.read()
                self.frames.append(((t1 + now()) / 2, jpg))
            except OSError:
                time.sleep(0.2)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join(timeout=5)


# ── ESPHome ──────────────────────────────────────────────────────────────────

async def press_button(host, key_b64, button, out):
    from aioesphomeapi import APIClient
    c = APIClient(host, 6053, None, noise_psk=key_b64)
    await c.connect(login=True)
    ents, _ = await c.list_entities_services()
    btn = next((e for e in ents if e.name == button), None)
    if btn is None:
        await c.disconnect()
        raise SystemExit(f"No button named {button!r}. Have: {[e.name for e in ents]}")
    logs = []
    c.subscribe_logs(lambda m: logs.append((now(), m.message.decode(errors="replace"))))
    await asyncio.sleep(0.5)
    out["press_time"] = now()
    c.button_command(btn.key)
    await asyncio.sleep(3.0)
    await c.disconnect()
    for t, msg in logs:
        m = re.search(r"RF TX ([01]{32})", msg)
        if m:
            out["device_tx_bits"], out["device_log_time"] = m.group(1), t


# ── analysis ─────────────────────────────────────────────────────────────────

def decode_sdr(t_start, env, noise_mult):
    floor = np.median(np.sort(env[:: 50])[: len(env[:: 50]) // 5])
    thr = floor * noise_mult
    hi = env > thr
    edges = np.flatnonzero(np.diff(hi.astype(np.int8))) + 1
    if len(edges) < 2:
        return {"threshold": float(thr), "peak": float(env.max()), "frames": []}
    if not hi[edges[0]]:
        edges = edges[1:]
    durs = np.diff(edges)  # alternating HIGH, LOW, HIGH, ... in us
    frames, cur, cur_start = [], [], None
    for i, d in enumerate(durs):
        if i % 2 == 1 and d >= 2000:  # sync gap ends a frame
            if len(cur) >= 64:
                frames.append((cur_start, cur, int(d)))
            cur, cur_start = [], None
            continue
        if cur_start is None:
            cur_start = t_start + edges[i] / SDR_RATE
        cur.append(int(d))
    result = []
    for start, p, gap in frames:
        pairs = [(p[2 * k], p[2 * k + 1]) for k in range(len(p) // 2)]
        bits = "".join("1" if h > l else "0" for h, l in pairs[:32])
        result.append({"t": round(start, 4), "bits": bits, "pulses": len(p), "gap_us": gap,
                       "short_us": int(np.median([min(h, l) for h, l in pairs[:32]])),
                       "long_us": int(np.median([max(h, l) for h, l in pairs[:32]]))})
    return {"threshold": float(thr), "peak": float(env.max()), "frames": result}


def find_beeps(t_start, audio, ref):
    """The fan's beep is a ~3.98 kHz tone (+40 dB over this room's noise,
    ~0.3 s, starting ~0.07 s after the first RF frame). Tracks the 3.7-4.3 kHz
    band against its level in the 2 s before ref; only fan commands beep."""
    n, hop = 2048, 480
    if len(audio) < n * 4:
        return [], None
    fr = np.lib.stride_tricks.sliding_window_view(audio, n)[::hop] * np.hanning(n)
    spec = 20 * np.log10(np.abs(np.fft.rfft(fr, axis=1)) + 1e-9)
    f = np.fft.rfftfreq(n, 1 / AUDIO_RATE)
    level = spec[:, (f > 3700) & (f < 4300)].max(axis=1)
    t = t_start + (np.arange(len(level)) * hop + n / 2) / AUDIO_RATE
    pre = (t > ref - 2.2) & (t < ref - 0.2) if ref is not None else np.ones(len(t), bool)
    rise = level - (np.percentile(level[pre], 95) if pre.any() else np.median(level))
    hit = rise > 15
    beeps, i = [], 0
    while i < len(hit):
        if hit[i]:
            j = i
            while j < len(hit) and hit[j]:
                j += 1
            if (j - i) * hop / AUDIO_RATE >= 0.08:
                beeps.append({"t": round(float(t[i]), 3), "dur_ms": int((j - i) * hop / AUDIO_RATE * 1000),
                              "rise_db": round(float(rise[i:j].max()), 1)})
            i = j
        else:
            i += 1
    return beeps, (t, rise)

def camera_stats(frames, press):
    stats = []
    prev = None
    for t, jpg in frames:
        g = np.asarray(Image.open(io.BytesIO(jpg)).convert("L"), dtype=np.float32)
        motion = float(np.abs(g - prev).mean()) if prev is not None and prev.shape == g.shape else None
        # Auto-exposure hides the light in the mean; the bulb shows as saturated pixels.
        stats.append({"t": round(t, 3), "light_px_pct": round(float((g > 240).mean() * 100), 2),
                      "motion": None if motion is None else round(motion, 2)})
        prev = g
    before = [s for s in stats if s["t"] < press]
    after = [s for s in stats if s["t"] > press + 2.0]

    def avg(rows, k):
        v = [r[k] for r in rows if r[k] is not None]
        return round(float(np.mean(v)), 2) if v else None
    return stats, {"light_px_pct_before": avg(before, "light_px_pct"), "light_px_pct_after": avg(after, "light_px_pct"),
                   "motion_before": avg(before, "motion"), "motion_after": avg(after, "motion")}


def plot(path, press, sdr_t0, env, thr, beep_curve, cam_stats, decoded, label):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    step = 200
    ax[0].plot(sdr_t0 + np.arange(0, len(env), step) / SDR_RATE, env[::step], lw=0.5)
    ax[0].axhline(thr, color="r", lw=0.5)
    for f in decoded:
        ax[0].axvline(f["t"], color="g", lw=0.3)
    ax[0].set_ylabel("SDR envelope")
    if beep_curve:
        ax[1].plot(beep_curve[0], beep_curve[1], lw=0.6)
    ax[1].axhline(15, color="r", lw=0.5)
    ax[1].set_ylabel("4 kHz beep band, dB")
    if cam_stats:
        ts = [s["t"] for s in cam_stats]
        ax[2].plot(ts, [s["light_px_pct"] for s in cam_stats], "o-", label="light px %")
        ax[2].plot(ts, [s["motion"] or 0 for s in cam_stats], "s-", label="motion")
        ax[2].legend()
    ax[2].set_ylabel("camera")
    ax[2].set_xlabel("seconds since start")
    for a in ax:
        if press is not None:
            a.axvline(press, color="k", ls="--")
    fig.suptitle(label)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--button", help="ESPHome button name, e.g. 'Fan 1 RF Speed 1'")
    g.add_argument("--remote", action="store_true", help="record only; press the real remote")
    ap.add_argument("--seconds", type=float, default=8, help="record time for --remote")
    ap.add_argument("--expect", help="32-bit code expected over the air")
    ap.add_argument("--host", default="fan-esphome.local")
    ap.add_argument("--cam", default="http://fan-cam.local:8080/")
    ap.add_argument("--mic", required=True, help="substring of the WASAPI microphone device name")
    ap.add_argument("--gain", type=int, default=40)
    ap.add_argument("--noise-mult", type=float, default=5)
    ap.add_argument("--settle", type=float, default=4.0, help="seconds to keep recording after the press")
    ap.add_argument("--video", action="store_true", help="encode timestamp-paced camera.mp4 with ffmpeg")
    args = ap.parse_args()

    label = args.button or "remote"
    run = ROOT / "runs" / f"{datetime.now():%Y%m%d_%H%M%S}_{re.sub(r'[^A-Za-z0-9]+', '_', label)}"
    run.mkdir(parents=True)
    out = {"label": label}

    sdr, mic, cam = SdrRecorder(433.92, args.gain), MicRecorder(args.mic), CamRecorder(args.cam)
    with ExitStack() as recorders:
        sdr.start()
        recorders.callback(sdr.stop)
        print(f"[{now():6.2f}] sdr started", flush=True)
        if not sdr.wait_ready():
            raise SystemExit("rtl_sdr.exe produced no samples (dongle busy or missing?)")
        print(f"[{now():6.2f}] sdr streaming", flush=True)
        mic.start()
        recorders.callback(mic.stop)
        cam.start()
        recorders.callback(cam.stop)
        print(f"[{now():6.2f}] mic + camera started", flush=True)
        time.sleep(2.0)  # baseline: idle RF, room noise, camera before-frames
        if args.button:
            key = re.search(r'api_encryption_key:\s*"([^"]+)"', (ROOT / "secrets.yaml").read_text()).group(1)
            asyncio.run(press_button(args.host, key, args.button, out))
            time.sleep(max(0.0, args.settle - 3.0))
        else:
            print(f"Recording {args.seconds:.0f}s: press the remote button now.", flush=True)
            out["press_time"] = None
            time.sleep(args.seconds)

    sdr_t0, env = sdr.envelope()
    dec = decode_sdr(sdr_t0, env, args.noise_mult)
    frames = dec["frames"]
    expect = args.expect or out.get("device_tx_bits")
    codes = Counter(f["bits"] for f in frames)
    out["sdr"] = {
        "frames": len(frames),
        "codes": dict(codes),
        "first_frame_t": frames[0]["t"] if frames else None,
        "short_us": int(np.median([f["short_us"] for f in frames])) if frames else None,
        "long_us": int(np.median([f["long_us"] for f in frames])) if frames else None,
        "gap_us": int(np.median([f["gap_us"] for f in frames])) if frames else None,
        "threshold": round(dec["threshold"], 2), "peak": round(dec["peak"], 2),
    }
    if expect:
        out["expect"] = expect
        out["sdr"]["frames_matching"] = codes.get(expect, 0)
    if out.get("press_time") is not None and frames:
        out["sdr"]["latency_s"] = round(frames[0]["t"] - out["press_time"], 3)

    a_t0, audio = mic.audio()
    from scipy.io import wavfile
    wavfile.write(run / f"audio_t{a_t0:.3f}.wav", AUDIO_RATE, audio)
    ref = out.get("press_time") or (frames[0]["t"] if frames else None)
    beeps, curve = find_beeps(a_t0, audio, ref)
    out["beeps"] = [b for b in beeps if ref is None or b["t"] > ref - 0.2]

    stats, cam_summary = camera_stats(cam.frames, ref if ref is not None else now())
    out["camera"] = dict(cam_summary, frames=len(cam.frames))
    out["timing"] = {
        "audio_start_s": a_t0, "sdr_start_estimate_s": sdr_t0,
        "camera_frame_times_s": [t for t, _ in cam.frames],
        "sdr_chunks": [{"arrival_s": t, "bytes": len(b)} for t, b in sdr.chunks],
    }
    for i, (t, jpg) in enumerate(cam.frames):
        (run / f"frame_{i:03d}_{t:07.3f}.jpg").write_bytes(jpg)
    if args.video and len(cam.frames) > 1:
        entries = []
        for i, (t, _) in enumerate(cam.frames):
            entries.append(f"file 'frame_{i:03d}_{t:07.3f}.jpg'")
            if i + 1 < len(cam.frames):
                entries.append(f"duration {cam.frames[i + 1][0] - t:.6f}")
        (run / "camera.ffconcat").write_text("\n".join(entries) + "\n")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "concat", "-safe", "0", "-i", "camera.ffconcat",
                        "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "camera.mp4"], cwd=run, check=True)
    if cam.frames and ref is not None:
        before = [f for f in cam.frames if f[0] < ref]
        after = cam.frames[-1]
        if before:
            (run / "before.jpg").write_bytes(before[-1][1])
        (run / "after.jpg").write_bytes(after[1])

    plot(run / "timeline.png", out.get("press_time"), sdr_t0, env, dec["threshold"],
         curve, stats, frames, label)
    out["frames_detail"] = frames
    (run / "summary.json").write_text(json.dumps(out, indent=2))
    out.pop("frames_detail")
    out.pop("timing")
    print(json.dumps(out, indent=2))
    print(f"run dir: {run}")


if __name__ == "__main__":
    main()

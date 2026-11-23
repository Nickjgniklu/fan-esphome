"""Regenerate the README evidence figures in docs/images from local recordings.

Optional maintainer tool. The inputs are local, git-ignored evidence, not part
of this repo:
  --fan-control  sibling fan_control checkout (real-remote Mainstays captures)
  --artika       sibling artika-fan-rf checkout (real-remote Artika .cu8)
  runs/          rf_bench.py recordings and the saved Artika replay capture.cu8

Outputs are privacy-safe derived plots plus camera frames cropped to the fan.
No audio or uncropped room imagery is written.

  python tools/make_readme_figures.py --fan-control ../fan_control --artika ../artika-fan-rf
"""
import argparse
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import uniform_filter1d

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
RUNS = ROOT / "runs"


def square_wave(durations_us, start_high=True):
    """Pulse widths (alternating HIGH/LOW) -> step-plot x (ms), y (0/1)."""
    t, level, xs, ys = 0.0, 1 if start_high else 0, [], []
    for d in durations_us:
        xs += [t / 1000, (t + d) / 1000]
        ys += [level, level]
        t += d
        level ^= 1
    return np.array(xs), np.array(ys)


def mainstays_capture(fan_control):
    cap = json.loads((fan_control / "tools" / "captures" / "fan3_speed1_sdr.json").read_text())
    burst, bits = cap["burst"][:65], cap["bits"]
    xs, ys = square_wave(burst)
    fig, ax = plt.subplots(figsize=(12, 3.2))
    ax.plot(xs, ys, color="#1f77b4", lw=1.2)
    t = 0.0
    for i, b in enumerate(bits):
        width = burst[2 * i] + burst[2 * i + 1]
        ax.text((t + width / 2) / 1000, 1.12, b, ha="center", fontsize=8, family="monospace")
        t += width
    bit_ms = sum(burst[:64]) / 32 / 1000
    for lo, hi, name, color in [(0, 16, "address (this remote)", "#d62728"),
                                (16, 20, "model 0x5", "#9467bd"),
                                (20, 28, "button byte", "#2ca02c"),
                                (28, 32, "XOR checksum", "#ff7f0e")]:
        ax.axvspan(lo * bit_ms, hi * bit_ms, color=color, alpha=0.10)
        ax.text((lo + hi) / 2 * bit_ms, -0.38, name, ha="center", fontsize=9, color=color)
    ax.set_ylim(-0.55, 1.3)
    ax.set_yticks([0, 1], ["LOW", "HIGH"])
    ax.set_xlabel("ms from frame start")
    ax.set_title("Mainstays real-remote CAPTURE (RTL-SDR, 1 MS/s): one 32-bit frame, Speed 1, "
                 "~274/768 µs pulses", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "mainstays-remote-capture.png", dpi=110)
    plt.close(fig)


def mainstays_bench():
    shutil.copy(RUNS / "20261120_150509_Fan_3_RF_Off" / "timeline.png", OUT / "mainstays-replay-bench.png")


def mainstays_light_camera():
    runs = [RUNS / n for n in ("20261120_161911_Fan_3_Light_On", "20261120_161922_Fan_3_Light_On",
                               "20261120_161933_Fan_3_Light_Off", "20261120_161943_Fan_3_Light_Off")]
    labels = ["Light On #1: now OFF", "Light On #2: now ON", "Light Off #1: now OFF", "Light Off #2: now ON"]
    crop, w, h = (0, 80, 360, 380), 240, 200  # fan only; excludes walls and window
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    out = Image.new("RGB", (4 * w, h + 28))
    draw = ImageDraw.Draw(out)
    for i, (run, label) in enumerate(zip(runs, labels)):
        out.paste(Image.open(run / "after.jpg").crop(crop).resize((w, h)), (i * w, 28))
        draw.text((i * w + 6, 5), label, fill="white", font=font)
    out.save(OUT / "mainstays-light-camera.jpg", quality=85)


def cu8_envelope(path, start_s, seconds):
    with open(path, "rb") as f:
        f.seek(int(start_s * 2e6))
        raw = np.frombuffer(f.read(int(seconds * 2e6)), dtype=np.uint8).astype(np.float32) - 127.5
    env = uniform_filter1d(np.hypot(raw[0::2], raw[1::2]), 20)
    thr = (np.percentile(env, 20) + np.percentile(env, 99.95)) / 2
    return env, thr


def artika_frame(path, first_frame_s):
    env, thr = cu8_envelope(path, first_frame_s - 0.002, 0.046)
    high = env > thr
    edges = np.flatnonzero(np.diff(high.astype(np.int8))) + 1
    start = edges[0]
    runs = np.diff(edges[:50])  # 24 bits * 2 + sync HIGH
    bits = "".join("1" if runs[2 * i] > runs[2 * i + 1] else "0" for i in range(24))
    t_ms = (np.arange(len(env)) - start) / 1000
    norm = env / np.percentile(env[high], 50)
    return t_ms, norm, bits, runs


def artika_compare(artika):
    remote = artika_frame(artika / "captures" / "session1_all_buttons.cu8", 83.292715)
    replay = artika_frame(RUNS / "20261123_101255_artika_replay" / "capture.cu8", 1.963241)
    fig, axes = plt.subplots(2, 1, figsize=(12, 4.8), sharex=True)
    for ax, (t, env, bits, runs), title, color in [
            (axes[0], remote, "Original remote CAPTURE (light toggle)", "#1f77b4"),
            (axes[1], replay, "ESP32 RF REPLAY of the same code, recorded by the same SDR", "#d62728")]:
        ax.plot(t, env, color=color, lw=0.7)
        pos = 0
        for i, b in enumerate(bits):
            width = runs[2 * i] + runs[2 * i + 1]
            ax.text((pos + width / 2) / 1000, 1.45, b, ha="center", fontsize=8, family="monospace")
            pos += width
        ax.set_ylim(-0.1, 1.7)
        ax.set_yticks([])
        ax.set_title(f"{title}: 0x{int(bits, 2):06X}", fontsize=10, loc="left")
    axes[1].set_xlabel("ms from frame start (normalised SDR envelope, 1 MS/s)")
    axes[1].set_xlim(-2, 44)
    fig.suptitle("Artika REM-ARTC-3: 24 data bits + sync HIGH, ~410/1220 µs pulses", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "artika-capture-vs-replay.png", dpi=110)
    plt.close(fig)
    assert remote[2] == replay[2] == format(0x562305, "024b"), (remote[2], replay[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fan-control", type=Path, required=True)
    ap.add_argument("--artika", type=Path, required=True)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    mainstays_capture(args.fan_control)
    mainstays_bench()
    mainstays_light_camera()
    artika_compare(args.artika)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()

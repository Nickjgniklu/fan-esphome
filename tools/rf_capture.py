"""SDR-only capture and analysis of a 433.92 MHz OOK remote.

Minimum tool for discovering a new remote's address or protocol: needs an
RTL-SDR, the native rtl_sdr program and numpy (matplotlib only for --plot).
No ESPHome device, microphone or camera. Adapted from the Artika investigation.

    python tools/rf_capture.py record my_remote_light --seconds 6
    python tools/rf_capture.py analyze runs/captures/my_remote_light.cu8 --plot out.png

record writes raw 8-bit IQ (.cu8, 1 MS/s) to runs/captures/ (git-ignored) and
analyzes it. analyze prints pulse-width histograms, every frame's bits (long
HIGH = 1), the modal code per press and the modal frame's HIGH/LOW durations.
Bits assume PWM OOK; check the histograms before trusting them.
Put rtl_sdr on PATH or set RTL_SDR_EXE to its full path. Close any other SDR user.
"""

import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

RTL_SDR_EXE = os.environ.get("RTL_SDR_EXE", "rtl_sdr")
FS = 1_000_000
CAPTURE_DIR = Path(__file__).resolve().parent.parent / "runs" / "captures"


def record(name, seconds, gain, freq_mhz):
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_DIR / f"{name}.cu8"
    n = int(FS * seconds) * 2
    cmd = [RTL_SDR_EXE, "-f", str(int(freq_mhz * 1e6)), "-s", str(FS), "-g", str(gain), "-n", str(n), str(path)]
    print(f"Recording {seconds}s at {freq_mhz} MHz -> {path}")
    print("Press the remote button about 2-3 s after this line (the dongle takes ~2 s to start).")
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode(errors="ignore"))
        sys.exit(f"rtl_sdr failed; is the dongle connected and RTL_SDR_EXE ({RTL_SDR_EXE}) correct?")
    return path


def envelope(path):
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    n = len(raw) // 2
    mag = np.empty(n, dtype=np.float32)
    step = 10_000_000
    for i in range(0, n, step):
        c = np.asarray(raw[2 * i : 2 * min(n, i + step)], dtype=np.float32) - 127.5
        mag[i : i + len(c) // 2] = np.hypot(c[0::2], c[1::2])
    k = 20  # 20 us moving average
    cs = np.concatenate(([0.0], np.cumsum(mag, dtype=np.float64)))
    out = np.empty(n, dtype=np.float32)
    out[k // 2 : n - k + k // 2 + 1] = (cs[k:] - cs[:-k]) / k
    out[: k // 2] = out[k // 2]
    out[n - k + k // 2 + 1 :] = out[n - k + k // 2]
    return out


def runs(binary):
    edges = np.flatnonzero(np.diff(binary)) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(binary)]))
    return [(int(binary[s]), int(e - s), int(s)) for s, e in zip(starts, ends)]


def analyze(path, plot=None, gap_us=4000, min_us=60):
    env = envelope(path)
    noise = np.percentile(env, 50)
    peak = np.percentile(env, 99.95)
    thr = noise + (peak - noise) * 0.5
    print(f"noise {noise:.1f}  peak {peak:.1f}  threshold {thr:.1f}  (SNR {20*np.log10(peak/max(noise,1e-6)):.1f} dB)")
    binary = (env > thr).astype(np.int8)
    merged = []  # drop glitches shorter than min_us by merging into neighbours
    for lvl, dur, start in runs(binary):
        if merged and (dur < min_us or merged[-1][0] == lvl):
            merged[-1] = (merged[-1][0], merged[-1][1] + dur, merged[-1][2])
        else:
            merged.append((lvl, dur, start))
    frames, cur = [], []  # split into frames at long LOW gaps
    for lvl, dur, start in merged:
        if lvl == 0 and dur >= gap_us:
            if cur:
                frames.append((cur, dur))
            cur = []
        elif lvl == 1 or cur:
            cur.append((lvl, dur, start))
    if cur:
        frames.append((cur, None))  # a final frame ends in silence, not at a gap
    frames = [(f, g) for f, g in frames if sum(1 for x in f if x[0] == 1) >= 8]
    print(f"{len(frames)} frames")
    if not frames:
        return None
    highs = [d for f, _ in frames for l, d, _ in f if l == 1]
    lows = [d for f, _ in frames for l, d, _ in f if l == 0]
    print("HIGH widths (us, rounded 20):", sorted(Counter(round(h, -1) // 20 * 20 for h in highs).items()))
    print("LOW widths  (us, rounded 20):", sorted(Counter(round(h, -1) // 20 * 20 for h in lows).items()))
    split_h = (min(highs) + max(highs)) / 2
    bitsets = []
    for i, (f, gap) in enumerate(frames):
        hs = [d for l, d, _ in f if l == 1]
        bits = "".join("1" if h > split_h else "0" for h in hs)  # PWM guess: long HIGH = 1
        bitsets.append(bits)
        print(f"[{i:2d}] t={f[0][2] / 1000:8.1f}ms  pulses={len(hs):3d}  gap_after={gap}  bits={bits}")
    presses, prev_t = [], None  # frames more than 300 ms apart start a new press
    for (f, _), bits in zip(frames, bitsets):
        t = f[0][2]
        if prev_t is None or t - prev_t > 300_000:
            presses.append([])
        presses[-1].append((t, bits))
        prev_t = t
    print(f"\n{len(presses)} presses:")
    for i, pr in enumerate(presses):
        b, n = Counter(b for _, b in pr).most_common(1)[0]
        print(f"  press {i+1:2d}  t={pr[0][0]/1e6:7.2f}s  frames={len(pr):3d}  modal({n}) {b}  ({len(b)} bits)")
    best, cnt = Counter(bitsets).most_common(1)[0]
    print(f"\nModal frame ({cnt}/{len(bitsets)}): {best}  ({len(best)} high pulses)")
    f = frames[bitsets.index(best)][0]
    print("Modal frame runs (level:us):", " ".join(f"{'H' if l else 'L'}{d}" for l, d, _ in f))
    if plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        s, e = f[0][2], f[-1][2] + f[-1][1]
        lo, hi = max(0, s - 3000), min(len(env), e + 3000)
        fig, ax = plt.subplots(2, 1, figsize=(16, 6))
        ax[0].plot(np.arange(len(env))[::50] / 1e6, env[::50], lw=0.4)
        ax[0].axhline(thr, color="r", ls="--")
        ax[0].set_xlabel("s")
        ax[1].plot((np.arange(lo, hi) - s) / 1000, env[lo:hi], lw=0.6)
        ax[1].axhline(thr, color="r", ls="--")
        ax[1].set_xlabel("ms from frame start")
        plt.tight_layout()
        plt.savefig(plot, dpi=110)
        print(f"plot -> {plot}")
    return best


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="capture with rtl_sdr, then analyze")
    r.add_argument("name")
    r.add_argument("--seconds", type=float, default=6)
    r.add_argument("--gain", type=int, default=40)
    r.add_argument("--freq", type=float, default=433.92)
    a = sub.add_parser("analyze", help="analyze an existing .cu8 capture")
    a.add_argument("path")
    a.add_argument("--plot")
    a.add_argument("--gap-us", type=int, default=4000)
    args = p.parse_args()
    if args.cmd == "record":
        path = record(args.name, args.seconds, args.gain, args.freq)
        analyze(path, plot=str(path.with_suffix(".png")))
    else:
        analyze(args.path, args.plot, args.gap_us)


if __name__ == "__main__":
    main()

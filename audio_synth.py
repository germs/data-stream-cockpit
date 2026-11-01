"""Synthesized temp soundtrack, driven by the animation itself. Writes four stems + a mix to audio/ (48 kHz stereo WAV).

  engine    rumble + engine tone following the real speed curve and turbulence, wind rush, boot power-up
  hud       screen power-ups, type-on ticks, scanning pings, contact alert, alarm pulses, lance charge, lock-on, countdown
  creature  KESTREL-9: power-up growl, hood servos and clacks, screech/hiss with the jaw, pass whoosh; panned and
            attenuated from its real position relative to the camera
  warp      spool-up whine, the jump boom, hyperspace roar and shimmer, exit swell

Run on the final file (it samples the animation, then synthesizes; numpy only):
  Blender --background data_stream_final.blend --python audio_synth.py -- [--frames 680]
"""
import bpy, math, os, sys, wave
import numpy as np
from mathutils import Vector

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
NF = int(ARGS[ARGS.index("--frames") + 1]) if "--frames" in ARGS else 680
SR, FPS = 48000, bpy.context.scene.render.fps
N = int(NF / FPS * SR)
rng = np.random.default_rng(7)
t = np.arange(N) / SR
fr = 1.0 + t * FPS                      # frame number at every sample (frame 1 starts at t = 0)
F = np.arange(1, NF + 1, dtype=float)

# ---------------------------------------------------------------- sample the animation
scene = bpy.context.scene
O = bpy.data.objects
cam, head, flight = O["Low flight camera"], O["KESTREL | Head"], O["KESTREL | Flight"]
turb, hud = O["COCKPIT | Turbulence"], O["HUD | Control"]
trav_obj = O["SPEED CONTROL"]
rows = []
for f in range(1, NF + 1):
    scene.frame_set(f)
    tv = trav_obj["travel"]
    hp = cam.matrix_world.inverted() @ head.matrix_world.translation
    rows.append((tv, turb["shake"], flight.scale.x > 0.5, hp.x, hp.y, hp.z, head["hood"], head["jaw"], head["tongue"]))
A = np.array(rows, dtype=float)
travel, shake, vis, cx, cy, cz, hood, jaw, tongue = A.T
vel = np.gradient(travel) * FPS                                  # m/s
v = np.clip(vel / 960.0, 0, 1.2)
dist = np.sqrt(cx ** 2 + cy ** 2 + cz ** 2)
print(f"sampled {NF} frames: top speed {vel.max():.0f} m/s, creature min distance {dist[vis > 0].min():.1f} m")


def env(arr):
    return np.interp(fr, F, arr)


def ramp(points):
    """[(frame, value), ...] -> per-sample envelope."""
    fs, vs = zip(*points)
    return np.interp(fr, fs, vs)


def shaped(x, lo, hi, tilt=0.0):
    """Band-shape a signal in the frequency domain; tilt < 0 darkens (pink = -0.5)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    f[0] = 1.0
    g = 1 / (1 + (lo / f) ** 4) / (1 + (f / hi) ** 4) * f ** tilt
    y = np.fft.irfft(X * g, len(x))
    return y / (np.abs(y).max() + 1e-9)


def stereo(x, pan=0.0):
    """Constant-power pan; pan may be a scalar or a per-sample array in [-1, 1]."""
    a = (np.clip(pan, -1, 1) + 1) * math.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)])


def place(buf, frame, sig):
    s = int((frame - 1) / FPS * SR)
    if s >= N:
        return
    e = min(N, s + sig.shape[-1])
    buf[:, s:e] += sig[:, : e - s]


def tone(freq, dur, amp=1.0, attack=0.004, decay=None, harmonics=(1.0,), sweep=None):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    fq = np.full(n, float(freq)) if sweep is None else np.geomspace(freq, sweep, n)
    ph = 2 * np.pi * np.cumsum(fq) / SR
    x = sum(h * np.sin(ph * (k + 1)) for k, h in enumerate(harmonics))
    e = np.minimum(1, tt / attack) * (np.exp(-tt / decay) if decay else np.minimum(1, (dur - tt) / 0.01))
    return amp * x * e


def burst(dur, lo, hi, amp=1.0, decay=0.05):
    n = int(dur * SR)
    x = shaped(rng.standard_normal(max(n, 64)), lo, hi)[:n]
    return amp * x * np.exp(-np.arange(n) / SR / decay)


def crackle(dur, amp=1.0):
    """Bit-crushed, sample-held noise: a digital glitch."""
    n = int(dur * SR)
    hold = rng.integers(40, 400)
    x = np.repeat(rng.uniform(-1, 1, n // hold + 1), hold)[:n]
    x = np.round(x * 4) / 4 * (rng.random(n) > 0.3)
    return amp * x * np.minimum(1, (dur - np.arange(n) / SR) / 0.01)


# ---------------------------------------------------------------- engine
power = ramp([(1, 0.0), (6, 0.25), (40, 1.0), (NF, 1.0)])
pre = ramp([(1, 1.0), (610, 1.0), (612, 0.0), (NF, 0.0)])        # the engine drops away into hyperspace
ve = env(v)
f0 = 30 + 85 * ve ** 0.8
ph = 2 * np.pi * np.cumsum(f0) / SR
osc = sum(0.85 ** k / (k + 1) * np.sin(ph * (k + 1)) for k in range(7)) + 0.5 * np.sin(ph * 1.503)
osc = np.tanh(1.6 * osc)
rumble = shaped(rng.standard_normal(N), 18, 160, tilt=-0.5) * (0.35 + 0.45 * np.clip(env(shake), 0, 2.5))
windL = shaped(rng.standard_normal(N), 350, 6000, tilt=-0.3)
windR = shaped(rng.standard_normal(N), 350, 6000, tilt=-0.3)
wamp = 0.45 * ve ** 1.6
core = power * pre * (0.32 * osc * (0.35 + 0.65 * ve) + 0.55 * rumble)
engine = np.stack([core + power * pre * wamp * windL, core + power * pre * wamp * windR])

# ---------------------------------------------------------------- hud
hudb = np.zeros((2, N))
BOOT = {"radar": (6, 0.0), "s1": (10, -0.25), "s2": (14, 0.25), "s0": (20, -0.6), "s3": (24, 0.6),
        "planet": (30, -0.45), "reticle": (34, 0.45)}
for name, (f, p) in BOOT.items():
    place(hudb, f + 1, stereo(burst(0.03, 1500, 9000, 0.5, 0.008), p))
    place(hudb, f + 2, stereo(tone(500, 0.12, 0.25, sweep=1300, harmonics=(1, 0.3)), p))
for f in range(16, 64):                                           # type-on chatter
    if rng.random() < 0.55:
        place(hudb, f + rng.random(), stereo(tone(rng.uniform(2200, 3400), 0.018, 0.08), rng.uniform(-0.6, 0.6)))
for f in range(39, 200, 36):                                      # SCANNING pings
    place(hudb, f, stereo(tone(1150, 0.9, 0.18, decay=0.25, harmonics=(1, 0.25)), 0.25))
for k in range(2):                                                # CONTACT
    place(hudb, 201 + k * 6, stereo(tone(880, 0.11, 0.3, harmonics=(1, 0.4, 0.2)), 0.25))
    place(hudb, 204 + k * 6, stereo(tone(660, 0.11, 0.3, harmonics=(1, 0.4, 0.2)), 0.25))
for f in range(380, 610, 20):                                     # alarm pulses with the red reactor
    place(hudb, f, stereo(tone(520, 0.16, 0.16, harmonics=(1, 0, 0.33, 0, 0.2)), -0.6))
for k in range(10):                                               # ion lance cells
    place(hudb, 380 + k * 12, stereo(tone(600 + k * 85, 0.07, 0.17, harmonics=(1, 0.3)), 0.6))
for k, fq in enumerate((660, 880, 1320)):                         # ARMED
    place(hudb, 500 + k, stereo(tone(fq, 0.35, 0.12, decay=0.15), 0.6))
lock_beeps = [430 - i * (i + 3) * 0.12 for i in range(8)][::-1]
for f in lock_beeps + [432, 434, 436, 437.5, 438.5, 439.3]:      # lock-on accelerates, then holds
    place(hudb, f, stereo(tone(1400, 0.04, 0.16), 0.45))
place(hudb, 440, stereo(tone(1600, 0.6, 0.2, decay=0.4, harmonics=(1, 0.5)), 0.45))
for f in (400, 401.5, 504, 561, 563):                             # glitches
    place(hudb, f, stereo(crackle(0.18, 0.35), rng.uniform(-0.5, 0.5)))
for f in (562, 572, 582, 592, 601):                               # countdown T-5..T-1
    place(hudb, f, stereo(tone(1000, 0.12, 0.28, harmonics=(1, 0.3)), 0.6))
place(hudb, 610, stereo(tone(1500, 0.25, 0.3, harmonics=(1, 0.3)), 0.6))

# ---------------------------------------------------------------- creature
pan = env(np.clip(cx / (np.abs(cz) + 6), -1, 1))
prox = env(vis * np.clip(28 / np.maximum(dist, 1), 0, 1.6))
wake = ramp([(1, 0), (190, 0), (215, 1), (NF, 1)])
fm = np.sin(2 * np.pi * 34 * t + 3.0 * np.sin(2 * np.pi * 17 * t))
growl = 0.35 * fm * (0.6 + 0.4 * np.sin(2 * np.pi * 6.5 * t)) * prox ** 0.8 * wake
hd = env(np.abs(np.gradient(hood)))
servo = 0.25 * np.clip(hd * 8, 0, 1) * np.sin(2 * np.pi * np.cumsum(380 + 600 * env(hood)) / SR) * env(vis)
jw = env(jaw)
scr_f = 1050 + 380 * np.sin(2 * np.pi * 3.1 * t) + 250 * env(tongue)
scr = np.sin(2 * np.pi * np.cumsum(scr_f) / SR + 4 * np.sin(2 * np.pi * 1730 * t))
hiss = shaped(rng.standard_normal(N), 2500, 11000)
screech = (0.22 * scr + 0.2 * hiss) * np.clip(jw - 0.2, 0, 1) * prox
whoosh = 0.6 * shaped(rng.standard_normal(N), 120, 2500, tilt=-0.4) * np.clip(prox - 0.35, 0, 1.2) ** 2
crea_mono = growl + servo + screech + whoosh
creature = stereo(crea_mono, pan)
for f0_, f1_ in ((405, 421), (592, 602)):                          # hood rib clacks
    for k in range(9):
        fk = f0_ + (f1_ - f0_) * k / 8
        i = min(N - 1, int((fk - 1) / FPS * SR))
        place(creature, fk, stereo(burst(0.025, 800, 6000, 0.35 * min(1.2, float(prox[i])), 0.006), float(pan[i])))

# ---------------------------------------------------------------- warp
warp = np.zeros((2, N))
u = np.clip((fr - 560) / 50, 0, 1)
spool_f = 180 * 12 ** (u ** 1.6)
trem = 0.75 + 0.25 * np.sin(2 * np.pi * np.cumsum(4 + 18 * u) / SR)
spool = (np.sin(2 * np.pi * np.cumsum(spool_f) / SR) + 0.4 * np.sin(4 * np.pi * np.cumsum(spool_f) / SR)) * u ** 1.5 * trem
spool *= ramp([(1, 1), (610, 1), (611.5, 0), (NF, 0)]) * 0.35
warp += stereo(spool)
n = int(2.6 * SR)
tt = np.arange(n) / SR
boom = np.sin(2 * np.pi * np.cumsum(28 + 95 * np.exp(-tt * 2.4)) / SR) * np.exp(-tt * 1.3)
boom += 0.6 * np.sin(2 * np.pi * 41 * tt) * np.exp(-tt * 0.9)
boom[: int(0.08 * SR)] += burst(0.08, 900, 14000, 1.0, 0.02)          # the snap
place(warp, 610.8, np.stack([boom, boom]) * 0.95)
hyper_amp = ramp([(1, 0), (610.8, 0), (612, 0.75), (660, 0.6), (680, 2.8), (NF, 2.8)])  # swells into the white-out
roarL = shaped(rng.standard_normal(N), 50, 7000, tilt=-0.5)
roarR = shaped(rng.standard_normal(N), 50, 7000, tilt=-0.5)
lfo = 0.8 + 0.2 * np.sin(2 * np.pi * 0.7 * t)
shimmer = sum(0.05 * np.sin(2 * np.pi * fq * t + 3 * np.sin(2 * np.pi * 0.3 * (k + 1) * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * (0.2 + 0.13 * k) * t))
              for k, fq in enumerate((1870, 2210, 2645, 3120, 3530, 4180)))
swell_u = np.clip((fr - 660) / 20, 0, 1)
swell = np.sin(2 * np.pi * np.cumsum(300 * 10 ** swell_u) / SR) * swell_u ** 2 * 0.5
warp += hyper_amp * np.stack([0.55 * roarL * lfo + shimmer + swell, 0.55 * roarR * lfo + shimmer + swell])

# ---------------------------------------------------------------- mix, level, write
GAIN = {"engine": 0.8, "hud": 0.55, "creature": 0.95, "warp": 1.0}
stems = {"engine": engine, "hud": hudb, "creature": creature, "warp": warp}
stems = {k: np.tanh(1.1 * s * GAIN[k]) for k, s in stems.items()}
fade = np.ones(N)
fade[-int(0.12 * SR):] = np.linspace(1, 0, int(0.12 * SR))
mix = sum(stems.values()) * fade
scale = 0.89 / np.abs(mix).max()                                  # peak at -1 dBFS; stems share the scale so they sum to the mix
os.makedirs(os.path.join(OUT, "audio"), exist_ok=True)


def write(name, x):
    pcm = (np.clip(x.T, -1, 1) * 32767).astype("<i2")
    with wave.open(os.path.join(OUT, "audio", f"{name}.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    rms = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
    print(f"WROTE audio/{name}.wav  peak {20 * np.log10(np.abs(x).max() + 1e-9):.1f} dBFS  rms {rms:.1f} dBFS")


for k, s in stems.items():
    write(f"stem_{k}", s * fade * scale)
write("temp_mix", mix * scale)
print(f"duration {N / SR:.2f} s = {NF} frames @ {FPS} fps")

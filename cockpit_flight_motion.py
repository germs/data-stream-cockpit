"""Make the cockpit fly: move the flight motion off the camera onto a cockpit body the camera rides in.

Before: SHIP | Flight motion -> Low flight camera (bank + lens) -> COCKPIT | Rig. The cockpit was glued to
the lens, so every camera move dragged the dash along with it and the cockpit never moved in frame.

After:
  SHIP | Flight motion            sway / bob (unchanged)
   COCKPIT | Body                 the bank that used to live on the camera
    COCKPIT | Turbulence          buffeting + engine vibration, scaled by its "shake" property (keyed per marker)
     COCKPIT | Mount              the pilot's eye (old camera rest orientation)
      COCKPIT | Rig               cockpit, same placement as before
      Low flight camera           the pilot's head: counter-roll, G-force push on acceleration, slight drift

Run on the cockpit file:
  Blender --background data_stream_cockpit.blend --python cockpit_flight_motion.py -- \
      [--bank 1.0] [--shake 1.0] [--head 1.0] [--render 1,300,504] [--percent 50] [--save NAME.blend]
--bank / --shake / --head scale the cockpit bank, turbulence and head motion.
"""
import bpy, math, os, sys
from bpy_extras import anim_utils

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


BANK = float(arg("--bank", "1.0"))
SHAKE = float(arg("--shake", "1.0"))
HEAD = float(arg("--head", "1.0"))

scene = bpy.context.scene
F0, F1 = scene.frame_start, scene.frame_end
ship = bpy.data.objects["SHIP | Flight motion"]
cam = bpy.data.objects["Low flight camera"]
rig = bpy.data.objects["COCKPIT | Rig"]
speed = bpy.data.objects["SPEED CONTROL"]
coll = bpy.data.collections["COCKPIT"]

if "COCKPIT | Body" in bpy.data.objects:
    sys.exit("cockpit_flight_motion: already applied to this file")


def channelbag(obj):
    ad = obj.animation_data
    return anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)


def fcurve(obj, path, index):
    return channelbag(obj).fcurves.find(path, index=index)


def empty(name, parent, size=0.2, hide=False):
    o = bpy.data.objects.new(name, None)
    o.empty_display_type = "ARROWS"
    o.empty_display_size = size
    coll.objects.link(o)
    o.parent = parent
    o.hide_render = hide
    return o


def add_noise(fc, scale, strength, phase):
    m = fc.modifiers.new("NOISE")
    m.scale, m.strength, m.phase, m.depth = scale, strength, phase, 1
    return m


# --- 1. Read the director's flight motion off the camera, then strip it -------------------------
rest = cam.matrix_local.copy()
base_pitch = cam.rotation_euler[0]
roll = {f: fcurve(cam, "rotation_euler", 1).evaluate(f) for f in range(F0, F1 + 1)}
yaw = {f: fcurve(cam, "rotation_euler", 2).evaluate(f) for f in range(F0, F1 + 1)}
bag = channelbag(cam)
for fc in [fc for fc in bag.fcurves if fc.data_path in ("rotation_euler", "location")]:
    bag.fcurves.remove(fc)

# --- 2. Cockpit body: sits at the eye, carries the bank ------------------------------------------
body = empty("COCKPIT | Body", ship, 0.5)
body.location = rest.translation
for f in range(F0, F1 + 1):
    body.rotation_euler = (0.0, roll[f] * BANK, yaw[f] * BANK)
    body.keyframe_insert("rotation_euler", frame=f)

# --- 3. Turbulence: noise source x "shake" envelope, via plain drivers (no autoexec needed) ------
noise = empty("COCKPIT | Turbulence noise", None, 0.1, hide=True)
noise.hide_viewport = True
noise.location = noise.rotation_euler = (0, 0, 0)
noise.keyframe_insert("location", frame=F0)
noise.keyframe_insert("rotation_euler", frame=F0)
# (channel, index): (buffet amplitude, vibration amplitude) at shake = 1. Body space: X right, Y forward, Z up.
deg = math.radians
NOISE_GAIN = 6.0  # Blender's noise modifier swings about +-strength/6, so this makes AMP the real peak
AMP = {
    ("location", 0): (0.020, 0.003),
    ("location", 2): (0.030, 0.004),
    ("rotation_euler", 0): (deg(0.45), deg(0.10)),   # pitch
    ("rotation_euler", 1): (deg(0.70), deg(0.08)),   # roll
    ("rotation_euler", 2): (deg(0.25), deg(0.05)),   # yaw
}
for i, ((path, idx), (buffet, vib)) in enumerate(AMP.items()):
    fc = fcurve(noise, path, idx)
    add_noise(fc, 22.0, buffet * NOISE_GAIN, 11.0 + i * 7.3)
    add_noise(fc, 1.6, vib * NOISE_GAIN, 53.0 + i * 3.1)

turb = empty("COCKPIT | Turbulence", body, 0.3)
turb["shake"] = 0.0
turb.id_properties_ui("shake").update(min=0.0, soft_max=2.0, description="Turbulence amount (keyed per marker)")
for f, v in ((F0, 0.10), (144, 0.22), (360, 0.55), (504, 1.0), (F1, 1.0)):
    turb["shake"] = v * SHAKE
    turb.keyframe_insert('["shake"]', frame=f)
for (path, idx) in AMP:
    d = turb.driver_add(path, idx).driver
    d.type = "SCRIPTED"
    n = d.variables.new(); n.name = "n"; n.targets[0].id = noise; n.targets[0].data_path = f"{path}[{idx}]"
    s = d.variables.new(); s.name = "s"; s.targets[0].id = turb; s.targets[0].data_path = '["shake"]'
    d.expression = "n * s"

# --- 4. Mount = old camera rest orientation; cockpit and camera both hang off it -----------------
mount = empty("COCKPIT | Mount", turb, 0.2)
mount.rotation_euler = (base_pitch, 0.0, 0.0)
rig.parent = mount  # rig's local transform (eye offset) is unchanged, so the cockpit sits exactly where it did
cam.parent = mount
cam.matrix_parent_inverse.identity()
cam.location = (0, 0, 0)
cam.rotation_euler = (0, 0, 0)

# --- 5. Pilot's head inside the cockpit (camera space: X right, Y up, Z back) --------------------
trav = fcurve(speed, '["travel"]', 0)
vel = {f: trav.evaluate(f + 0.5) - trav.evaluate(f - 0.5) for f in range(F0 - 15, F1 + 16)}
acc = {f: vel[min(f + 1, F1 + 15)] - vel[max(f - 1, F0 - 15)] for f in vel}
W = 10  # smoothing window: the body reacts, it doesn't twitch
g = {f: sum(acc[k] for k in range(f - W, f + W + 1) if k in acc) / (2 * W + 1) for f in range(F0, F1 + 1)}
gmax = max(abs(v) for v in g.values()) or 1.0
for f in range(F0, F1 + 1, 2):
    gn = max(0.0, g[f] / gmax) ** 0.7
    cam.location = (0.0, -0.012 * gn * HEAD, 0.05 * gn * HEAD)            # pushed back + down into the seat
    cam.rotation_euler = (deg(1.1) * gn * HEAD, 0.0, 0.4 * roll[f] * BANK * HEAD)  # chin up, head counter-rolls
    cam.keyframe_insert("location", frame=f)
    cam.keyframe_insert("rotation_euler", frame=f)
for i, (path, idx, amp) in enumerate((("rotation_euler", 0, deg(0.15)), ("rotation_euler", 1, deg(0.2)),
                                      ("rotation_euler", 2, deg(0.1)), ("location", 0, 0.004), ("location", 1, 0.004))):
    add_noise(fcurve(cam, path, idx), 40.0, amp * NOISE_GAIN * HEAD, 101.0 + i * 5.7)

print(f"FLIGHT MOTION bank={BANK} shake={SHAKE} head={HEAD} gmax={gmax:.3f}")

# --- 6. Optional check renders / save --------------------------------------------------------------
frames = arg("--render")
if frames:
    r = scene.render
    saved = (r.resolution_percentage, r.filepath, getattr(r.image_settings, "media_type", None), r.image_settings.file_format)
    if saved[2] is not None:
        r.image_settings.media_type = "IMAGE"
    r.image_settings.file_format = "PNG"
    r.resolution_percentage = int(arg("--percent", "50"))
    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
    for f in map(int, frames.split(",")):
        scene.frame_set(f)
        r.filepath = os.path.join(OUT, "renders", f"flight_motion_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    r.resolution_percentage, r.filepath = saved[0], saved[1]
    if saved[2] is not None:
        r.image_settings.media_type = saved[2]
    r.image_settings.file_format = saved[3]

if arg("--save"):
    scene.frame_set(F0)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, arg("--save")), copy=True)
    print("SAVED", arg("--save"))

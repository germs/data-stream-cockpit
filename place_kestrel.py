"""Put KESTREL-9 in the shot: it is the HUD's contact. We overtake it on the right; the lock lands as we pass its head.

  ~190-215  powers its lights up on the horizon (~350 m out, right of centre) as CONTACT KESTREL-9 types on
  200-360   we gain on it slowly; it dips toward the right-hand ridge line around frame 300
  360-430   we close fast; it climbs into the canopy window, the hood flares, the head turns toward the cockpit
  436-452   close pass overhead-right (~10 m): jaw open, tongue flicking, green light on the dash, a turbulence bump
  452-520   the body streams past above the canopy and falls behind

The path is keyed on `KESTREL | Flight` (the head's position, world space; the ship flies at the origin and the
world slides past). Retime the pass by sliding its keys; hood/jaw/tongue keys live on `KESTREL | Head`.

Run on the HUD file:
  Blender --background data_stream_cockpit_hud.blend --python place_kestrel.py -- \
      [--render 210,300,400,430,440,452] [--percent 50] [--save NAME.blend]
"""
import bpy, math, os, sys
from mathutils import Vector

OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, OUT)
import creature_kestrel as ck  # noqa: E402
from bpy_extras import anim_utils  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


scene = bpy.context.scene
D = math.radians
if "KESTREL | Flight" in bpy.data.objects:
    sys.exit("place_kestrel: already applied to this file")


def channelbag(idb):
    ad = idb.animation_data
    return anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)


def keys(idb, path, pairs, index=-1, interp="BEZIER"):
    for f, v in pairs:
        if path.startswith('["'):
            idb[path[2:-2]] = v
        elif index >= 0:
            getattr(idb, path)[index] = v
        else:
            setattr(idb, path, v)
        idb.keyframe_insert(path, index=index, frame=f)
        fc = channelbag(idb).fcurves.find(path, index=max(index, 0))
        for kp in fc.keyframe_points:
            if abs(kp.co.x - f) < 0.01:
                kp.interpolation = interp


# ---------------------------------------------------------------- build and rig
body, head = ck.build(scene)
root_coll = bpy.data.collections["KESTREL-9"]
flight = bpy.data.objects.new("KESTREL | Flight", None)
flight.empty_display_type = "SPHERE"
flight.empty_display_size = 3
root_coll.objects.link(flight)
body.parent = flight
body.location = (0, -ck.LENGTH, 0)  # the flight empty sits at the head

# ---------------------------------------------------------------- path (head position)
# Art-directed in camera terms so the head stays in the open canopy window (above the dash, inside the arch):
#   ("ndc", distance ahead m, screen x 0..1, screen y 0..1)  or  ("cam", x right, y up, z back) in camera space.
# Each key is converted to world space with the camera as it is on that frame.
PATH = [
    (189, ("ndc", 365, 0.60, 0.50), 0),
    (200, ("ndc", 350, 0.60, 0.50), 0),
    (260, ("ndc", 300, 0.61, 0.48), 0),
    (300, ("ndc", 255, 0.63, 0.44), 0),    # dips toward the right-hand ridge line
    (340, ("ndc", 205, 0.62, 0.50), 0),
    (360, ("ndc", 170, 0.62, 0.53), 0),
    # it turns on us: the head swings round to face the cockpit (yaw 180 = straight at us), the body sweeps
    # out to the right and away, so the face, not the back of the hood, is what we pass
    (380, ("ndc", 140, 0.63, 0.56), 15),
    (410, ("ndc", 80, 0.64, 0.60), 60),
    (425, ("ndc", 45, 0.66, 0.63), 105),   # hood flaring
    (436, ("ndc", 26, 0.67, 0.64), 128),
    (441, ("ndc", 18, 0.70, 0.645), 138),  # LOCK
    (446, ("ndc", 10, 0.80, 0.66), 142),
    (452, ("cam", 10.0, 7.5, 2.0), 140),   # overhead-right, passing the canopy
    (470, ("cam", 12.0, 8.5, 45.0), 120),
    (500, ("cam", 15.0, 10.0, 130.0), 100),
    (520, ("cam", 17.0, 11.0, 200.0), 90),
]
cam = scene.camera
cd = cam.data
aspect = scene.render.resolution_y / scene.render.resolution_x
for f, (mode, a, b, c), yaw in PATH:
    scene.frame_set(f)
    if mode == "ndc":
        d, nx, ny = a, b, c
        local = Vector(((nx - 0.5) * d * cd.sensor_width / cd.lens, (ny - 0.5) * d * cd.sensor_width * aspect / cd.lens, -d))
    else:
        local = Vector((a, b, c))
    keys(flight, "location", [(f, tuple(cam.matrix_world @ local))])
    keys(flight, "rotation_euler", [(f, D(yaw))], index=2)
# it banks into the turn and dips its nose to look down into the cockpit
keys(flight, "rotation_euler", [(1, 0.0), (380, 0.0), (430, D(-14)), (450, D(-12)), (500, 0.0)], index=1)
keys(flight, "rotation_euler", [(1, 0.0), (410, 0.0), (436, D(-16)), (450, D(-20)), (480, 0.0)], index=0)
# nothing exists before it powers up, nothing after it is gone
keys(flight, "scale", [(1, (0.0001,) * 3), (189, (0.0001,) * 3), (190, (1.0,) * 3), (530, (1.0,) * 3), (531, (0.0001,) * 3)],
     interp="CONSTANT")

# ---------------------------------------------------------------- performance: hood, jaw, tongue, eyes
keys(head, '["hood"]', [(1, 0.0), (400, 0.0), (418, 1.08), (424, 1.0), (470, 1.0), (500, 0.0)])
keys(head, '["jaw"]', [(1, 0.0), (418, 0.0), (430, 0.85), (452, 0.85), (470, 0.0)])
keys(head, '["tongue"]', [(1, 0.0), (424, 0.0)] + [(f, 1.0 if (f // 4) % 2 == 0 else 0.15) for f in range(428, 456, 4)] +
     [(460, 0.0)], interp="LINEAR")
eye = bpy.data.objects["KESTREL | Eye light"].data
keys(eye, "energy", [(1, 0.0), (190, 0.0), (215, 250.0), (405, 250.0), (432, 9000.0), (452, 9000.0), (470, 250.0)])


# lights come on: the glow materials ramp up as the contact registers
def emission_socket(m):
    for n in m.node_tree.nodes:
        if n.bl_idname == "ShaderNodeEmission":
            return n.inputs["Strength"]
        if n.bl_idname == "ShaderNodeBsdfPrincipled" and n.inputs["Emission Strength"].default_value > 0:
            return n.inputs["Emission Strength"]


for name in ("KESTREL Green Glow", "KESTREL Eye Glow", "KESTREL Lime Plate", "KESTREL Tongue Red"):
    m = bpy.data.materials[name]
    s = emission_socket(m)
    full = s.default_value
    for f, v in ((1, 0.0), (190, 0.0), (196, full * 1.6), (199, full * 0.2), (203, full * 1.2), (215, full)):
        s.default_value = v
        s.keyframe_insert("default_value", frame=f)
    s.default_value = full

# ---------------------------------------------------------------- moonlight on the creature only (light linking)
sun = bpy.data.lights.new("KESTREL Moonlight", "SUN")
sun.energy, sun.color, sun.angle = 4.0, (0.55, 0.7, 1.0), D(3)
so = bpy.data.objects.new("KESTREL | Moonlight", sun)
root_coll.objects.link(so)
so.rotation_euler = (D(-50), D(20), D(200))
link = bpy.data.collections.new("KESTREL | Moonlight receivers")
link.objects.link(body)
for o in root_coll.objects:
    if o.type == "MESH" and o.name not in link.objects:
        link.objects.link(o)
so.light_linking.receiver_collection = link

# ---------------------------------------------------------------- the wake: a turbulence bump as we pass
turb = bpy.data.objects["COCKPIT | Turbulence"]
fc = channelbag(turb).fcurves.find('["shake"]')
base = {f: fc.evaluate(f) for f in (432, 458)}
keys(turb, '["shake"]', [(432, base[432]), (440, base[432] + 1.0), (446, base[432] + 0.6), (458, base[458])])

print("KESTREL placed")

# ---------------------------------------------------------------- optional check renders / save
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
        r.filepath = os.path.join(OUT, "renders", f"kestrel_shot_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    r.resolution_percentage, r.filepath = saved[0], saved[1]
    if saved[2] is not None:
        r.image_settings.media_type = saved[2]
    r.image_settings.file_format = saved[3]

if arg("--save"):
    scene.frame_set(scene.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, arg("--save")), copy=True)
    print("SAVED", arg("--save"))

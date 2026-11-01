"""Animate the cockpit screens and holograms across the flight markers.

  01 Slow glide (1-143)        boot: screens flicker on centre-out, text types on, holograms pop in; calm idle
  02 Gathering speed (144-359) live velocity readout, thrust/reactor bars, gauges; contact KESTREL-9 appears, reticle hunts
  03 Acceleration (360-503)    CORE BOOST + red alert, ion lance charges, reticle locks, big screen glitch at HIT, shield drops
  04 Maximum velocity (504-)   readouts pinned, ARMED blinks, lock pulses, holograms jitter with the turbulence

Everything renders without Python: per-screen power and alert live on `HUD | Control` (custom props, keyed) and reach
materials and lights through simple drivers; text is Geometry Nodes ("HUD Text") so numbers and type-on are plain inputs.

Run on the flight file:
  Blender --background data_stream_cockpit_flight.blend --python cockpit_hud_animation.py -- \
      [--render 20,90,250,450,560] [--percent 50] [--save NAME.blend]
"""
import bpy, math, os, random, sys
from bpy_extras import anim_utils

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


scene = bpy.context.scene
FPS = scene.render.fps
F0, F1 = scene.frame_start, scene.frame_end
M2, M3, M4 = 144, 360, 504              # marker frames: gathering speed, acceleration, maximum velocity
CONTACT, LOCK = 200, 440               # KESTREL-9 shows up; reticle locks
HIT = 400                              # the big screen glitch, inside the Acceleration beat
OB = bpy.data.objects
rig = OB["COCKPIT | Rig"]
coll = bpy.data.collections["COCKPIT"]
random.seed(9)

if "HUD | Control" in OB:
    sys.exit("cockpit_hud_animation: already applied to this file")


# ---------------------------------------------------------------- keyframe / driver helpers
def channelbag(idb):
    ad = idb.animation_data
    return anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)


def key(idb, path, frame, value, index=-1, interp="BEZIER"):
    """Set idb.<path>[index] = value and key it with the given interpolation."""
    if path.startswith('["'):
        idb[path[2:-2]] = value
    elif "." in path:
        owner, attr = path.rsplit(".", 1)
        setattr(idb.path_resolve(owner), attr, value)
    else:
        prop = getattr(idb, path)
        if index >= 0:
            prop[index] = value
        else:
            setattr(idb, path, value)
    idb.keyframe_insert(path, index=index, frame=frame)
    fc = channelbag(idb).fcurves.find(path, index=max(index, 0))
    for kp in fc.keyframe_points:
        if abs(kp.co.x - frame) < 0.01:
            kp.interpolation = interp
    return fc


def keys(idb, path, pairs, index=-1, interp="BEZIER"):
    fc = None
    for f, v in pairs:
        fc = key(idb, path, f, v, index, interp)
    return fc


def drive(owner, path, expr, index=-1, **vars_):
    """vars_: name=(id, data_path). Expressions stay 'simple' so no autoexec is needed."""
    d = (owner.driver_add(path, index) if index >= 0 else owner.driver_add(path)).driver
    d.type = "SCRIPTED"
    for name, (idb, dp) in vars_.items():
        v = d.variables.new()
        v.name = name
        v.targets[0].id_type = "OBJECT"
        v.targets[0].id = idb
        v.targets[0].data_path = dp
    d.expression = expr
    return d


def descendants(o):
    out = []
    for c in o.children:
        out += [c] + descendants(c)
    return out


# ---------------------------------------------------------------- HUD control
hud = OB.new("HUD | Control", None)
hud.empty_display_type = "PLAIN_AXES"
hud.empty_display_size = 0.05
coll.objects.link(hud)
hud.parent = rig
hud.hide_render = True
hud.location = (0, 0.6, 1.4)
GROUPS = {"s0": "Screen 0", "s1": "Screen 1", "s2": "Screen 2", "s3": "Screen 3",
          "radar": "Radar", "planet": "Holo Planet", "reticle": "Holo Reticle"}
for g in GROUPS:
    hud["p_" + g] = 0.0
for p, v in (("alert", 0.0), ("glitch", 0.0), ("speed", 0.0), ("thrust", 0.0), ("range_km", 2.4), ("shield", 30.0)):
    hud[p] = v

# ---------------------------------------------------------------- speed, from the flight's travel curve
trav = channelbag(OB["SPEED CONTROL"]).fcurves.find('["travel"]')
fwd = lambda f: min(max(f + 0.5, F0 + 1), F1)  # stay inside the keyed range so the ends don't read half speed
speed = {f: (trav.evaluate(fwd(f)) - trav.evaluate(fwd(f) - 1)) * FPS for f in range(F0 - 12, F1 + 13)}
acc = {f: speed[f + 1] - speed[f - 1] for f in range(F0 - 11, F1 + 12)}
gsm = {f: sum(acc[k] for k in range(f - 10, f + 11) if k in acc) / 21 for f in range(F0, F1 + 1)}
GPEAK = max(gsm, key=gsm.get)  # the G-force hit the flight rig pushes the pilot's head on
VMAX = max(speed[f] for f in range(F0, F1 + 1))
for f in range(F0, F1 + 1, 2):
    v = speed[f] * (1 + (random.uniform(-0.004, 0.004) if f >= M4 else 0))
    key(hud, '["speed"]', f, round(v), interp="CONSTANT")
    key(hud, '["thrust"]', f, (speed[f] / VMAX) ** 0.6, interp="LINEAR")
print(f"HUD speed max {VMAX:.0f} m/s, G peak frame {GPEAK}")


# ---------------------------------------------------------------- materials: per-group copies with power (+ alert)
def value_node(nt, prop, loc):
    n = nt.nodes.new("ShaderNodeValue")
    n.location = loc
    drive(n.outputs[0], "default_value", "p", p=(hud, f'["{prop}"]'))
    return n


def powered(mat, group):
    """Copy of mat whose emission strength is multiplied by HUD p_<group>; s0 also tints toward red on alert."""
    name = f"{mat.name} | {group}"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    m = mat.copy()
    m.name = name
    nt = m.node_tree
    em = next((n for n in nt.nodes if n.bl_idname in ("ShaderNodeEmission", "ShaderNodeBsdfPrincipled")), None)
    if em is None:
        return m
    sock = em.inputs["Strength" if em.bl_idname == "ShaderNodeEmission" else "Emission Strength"]
    pw = value_node(nt, "p_" + group, (em.location.x - 500, em.location.y - 250))
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.location = (em.location.x - 250, em.location.y - 200)
    if sock.is_linked:
        nt.links.new(sock.links[0].from_socket, mul.inputs[0])
    else:
        mul.inputs[0].default_value = sock.default_value
    nt.links.new(pw.outputs[0], mul.inputs[1])
    nt.links.new(mul.outputs[0], sock)
    if group == "s0":
        csock = em.inputs["Color" if em.bl_idname == "ShaderNodeEmission" else "Emission Color"]
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.location = (em.location.x - 250, em.location.y + 150)
        rgba = lambda socks, nm: next(s for s in socks if s.name == nm and s.type == "RGBA")
        rgba(mix.inputs, "A").default_value = csock.default_value
        rgba(mix.inputs, "B").default_value = (1.0, 0.07, 0.03, 1)
        drive(next(s for s in mix.inputs if s.name == "Factor" and s.type == "VALUE"), "default_value", "a",
              a=(hud, '["alert"]'))
        nt.links.new(rgba(mix.outputs, "Result"), csock)
    # scanlines on the glass roll slowly, and jump on a glitch
    for n in nt.nodes:
        if n.bl_idname == "ShaderNodeTexWave":
            drive(n.inputs["Phase Offset"], "default_value", "frame * 0.12 + g * 30", g=(hud, '["glitch"]'))
    return m


GLOWY = ("Glow", "Holo", "Halo", "Screen Glass", "Strip")
for g, anchor in GROUPS.items():
    for o in descendants(OB[anchor]):
        for slot in o.material_slots:
            if slot.material and slot.material.name.startswith(GLOWY):
                slot.material = powered(slot.material, g)
for i in range(4):
    drive(OB[f"Screen Spill {i}"].data, "energy", f"{OB[f'Screen Spill {i}'].data.energy} * p", p=(hud, f'["p_s{i}"]'))
drive(OB["Radar Glow"].data, "energy", f"{OB['Radar Glow'].data.energy} * p", p=(hud, '["p_radar"]'))

# ---------------------------------------------------------------- HUD Text: Geometry Nodes text with type-on + numbers
FONT = next(o.data.font for o in OB if o.type == "FONT")
gt = bpy.data.node_groups.new("HUD Text", "GeometryNodeTree")
gt.is_modifier = True
S = {}
for nm, typ, dv in (("Text", "NodeSocketString", ""), ("Prefix", "NodeSocketString", ""), ("Suffix", "NodeSocketString", ""),
                    ("Use Number", "NodeSocketBool", False), ("Number", "NodeSocketFloat", 0.0), ("Decimals", "NodeSocketInt", 0),
                    ("Reveal", "NodeSocketFloat", 1.0), ("Size", "NodeSocketFloat", 0.02), ("Material", "NodeSocketMaterial", None)):
    s = gt.interface.new_socket(nm, in_out="INPUT", socket_type=typ)
    if dv is not None:
        s.default_value = dv
    S[nm] = s.identifier
gt.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
N, L = gt.nodes, gt.links
gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
v2s = N.new("FunctionNodeValueToString")
L.new(gi.outputs["Number"], v2s.inputs["Value"])
L.new(gi.outputs["Decimals"], v2s.inputs["Decimals"])
j1, j2 = N.new("GeometryNodeStringJoin"), N.new("GeometryNodeStringJoin")
# multi-input sockets list the newest link first, so link each join back to front
L.new(v2s.outputs["String"], j1.inputs["Strings"])
L.new(gi.outputs["Prefix"], j1.inputs["Strings"])
L.new(gi.outputs["Suffix"], j2.inputs["Strings"])
L.new(j1.outputs[0], j2.inputs["Strings"])
sw = N.new("GeometryNodeSwitch")
sw.input_type = "STRING"
L.new(gi.outputs["Use Number"], sw.inputs["Switch"])
L.new(gi.outputs["Text"], sw.inputs["False"])
L.new(j2.outputs[0], sw.inputs["True"])
s2c = N.new("GeometryNodeStringToCurves")
s2c.inputs["Font"].default_value = FONT  # Blender 5.x: font and alignment are sockets
s2c.inputs["Align X"].default_value = "Center"
s2c.inputs["Align Y"].default_value = "Middle"
L.new(sw.outputs[0], s2c.inputs["String"])
L.new(gi.outputs["Size"], s2c.inputs["Size"])
cnt = N.new("GeometryNodeAttributeDomainSize")
cnt.component = "INSTANCES"
L.new(s2c.outputs["Curve Instances"], cnt.inputs[0])
shown = N.new("ShaderNodeMath"); shown.operation = "MULTIPLY"
L.new(cnt.outputs["Instance Count"], shown.inputs[0])
L.new(gi.outputs["Reveal"], shown.inputs[1])
idx = N.new("GeometryNodeInputIndex")
hide = N.new("FunctionNodeCompare"); hide.data_type = "FLOAT"; hide.operation = "GREATER_EQUAL"
L.new(idx.outputs[0], hide.inputs["A"])
L.new(shown.outputs[0], hide.inputs["B"])
dele = N.new("GeometryNodeDeleteGeometry"); dele.domain = "INSTANCE"
L.new(s2c.outputs["Curve Instances"], dele.inputs["Geometry"])
L.new(hide.outputs[0], dele.inputs["Selection"])
real = N.new("GeometryNodeRealizeInstances")
L.new(dele.outputs[0], real.inputs[0])
fill = N.new("GeometryNodeFillCurve")
L.new(real.outputs[0], fill.inputs["Curve"])
setm = N.new("GeometryNodeSetMaterial")
L.new(fill.outputs[0], setm.inputs["Geometry"])
L.new(gi.outputs["Material"], setm.inputs["Material"])
L.new(setm.outputs[0], go.inputs[0])
for k, n in enumerate((gi, v2s, j1, j2, sw, s2c, cnt, shown, idx, hide, dele, real, fill, setm, go)):
    n.location = (k * 180, 0)


def ipath(sock):
    """Blender 5.x path to a HUD Text modifier input value (animatable)."""
    return f'modifiers["HUD Text"].properties.inputs.{S[sock]}.value'


def iset(o, sock, value):
    getattr(o.modifiers["HUD Text"].properties.inputs, S[sock]).value = value


def iget(o, sock):
    return getattr(o.modifiers["HUD Text"].properties.inputs, S[sock]).value


def hud_text(src, text=None, number=None, prefix="", suffix="", decimals=0, name=None):
    """Replace font object src (or clone it under a new name) by a HUD Text mesh with the same placement."""
    me = bpy.data.meshes.new(name or src.name)
    o = OB.new(name or src.name, me)
    for c in src.users_collection:
        c.objects.link(o)
    o.parent = src.parent
    o.matrix_parent_inverse = src.matrix_parent_inverse
    o.location, o.rotation_euler, o.scale = src.location, src.rotation_euler, src.scale
    mod = o.modifiers.new("HUD Text", "NODES")
    mod.node_group = gt
    iset(o, "Text", text if text is not None else src.data.body)
    iset(o, "Size", src.data.size)
    iset(o, "Material", src.active_material)
    if number is not None:
        iset(o, "Use Number", True)
        iset(o, "Prefix", prefix)
        iset(o, "Suffix", suffix)
        iset(o, "Decimals", decimals)
        drive(o, ipath("Number"), "v", v=(hud, f'["{number}"]'))
    return o


def reveal(o, pairs, interp="LINEAR"):
    return keys(o, ipath("Reveal"), pairs, interp=interp)


def type_on(o, start, rate=1.0):
    n = max(1, len(iget(o, "Text").replace(" ", "")))
    reveal(o, ((F0, 0.0), (start, 0.0), (start + n * rate, 1.0)))


fonts = [o for o in OB if o.type == "FONT"]
T = {}
for src in fonts:
    nm = src.name
    if nm == "S1 Main":
        T[nm] = hud_text(src, number="speed", suffix=" m/s", name=nm + " ")
    elif nm == "S2 Shd":
        T[nm] = hud_text(src, number="shield", prefix="SHIELD ", suffix="%", name=nm + " ")
    elif nm == "Holo Reticle Label":
        T[nm] = hud_text(src, number="range_km", prefix="RANGE  ", suffix=" km", decimals=1, name=nm + " ")
        T["Holo Reticle Lock"] = hud_text(src, number="range_km", prefix="LOCK  ", suffix=" km", decimals=1, name="Holo Reticle Lock")
    else:
        T[nm] = hud_text(src, name=nm + " ")
        if nm == "S0 Main":
            T["S0 Boost"] = hud_text(src, text="CORE  BOOST", name="S0 Boost")
        if nm == "S2 Title":
            T["S2 Scan"] = hud_text(src, text="SCANNING", name="S2 Scan")
for src in fonts:
    cu = src.data
    OB.remove(src)
    bpy.data.curves.remove(cu)
for nm, o in T.items():
    o.name = nm.strip()

# ---------------------------------------------------------------- 01 boot: power flicker, centre-out
BOOT = {"radar": 6, "s1": 10, "s2": 14, "s0": 20, "s3": 24, "planet": 30, "reticle": 34}
FLICKER = ((0, 1.4), (2, 0.1), (4, 0.9), (6, 0.15), (7, 1.0))
for g, b in BOOT.items():
    pairs = [(F0, 0.0), (b, 0.0)] + [(b + 1 + df, v) for df, v in FLICKER]
    keys(hud, f'["p_{g}"]', pairs, interp="CONSTANT")
    # big glitch mid-acceleration (screens only), and a smaller echo when max velocity kicks in
    if g.startswith("s"):
        jit = int(g[1]) % 2
        for at, depth in ((HIT + jit, 0.25), (M4 + jit, 0.6)):
            keys(hud, f'["p_{g}"]', ((at, depth), (at + 1, 1.5), (at + 3, 0.4), (at + 5, 1.0)), interp="CONSTANT")
keys(hud, '["glitch"]', ((F0, 0.0), (HIT, 1.0), (HIT + 2, 0.4), (HIT + 3, 1.0), (HIT + 6, 0.0),
                         (M4, 0.6), (M4 + 3, 0.0)), interp="CONSTANT")

# text type-on, after each screen powers up
for nm, delay in (("S0 Title", 5), ("S0 L0", 9), ("S0 L1", 11), ("S0 L2", 13), ("S1 Title", 5), ("S1 Main", 12),
                  ("S2 Scan", 5), ("S2 Hull", 12), ("S2 Shd", 16), ("S3 Title", 5), ("S3 Sub", 12), ("Holo Planet Label", 6)):
    grp = {"S0": "s0", "S1": "s1", "S2": "s2", "S3": "s3", "Ho": "planet"}[nm[:2]]
    type_on(T[nm], BOOT[grp] + delay, 0.8)
type_on(T["S0 Main"], BOOT["s0"] + 14, 0.8)
reveal(T["S0 Main"], ((M3 + 20, 1.0), (M3 + 21, 0.0), (M3 + 23, 1.0), (M3 + 24, 0.0)), interp="CONSTANT")   # STABLE -> BOOST swap
reveal(T["S0 Boost"], ((F0, 0.0), (M3 + 21, 0.0), (M3 + 22, 1.0), (M3 + 23, 0.0), (M3 + 24, 1.0)), interp="CONSTANT")
# SCANNING blinks until the contact, then the contact title types on
blink = [(f, 1.0 if (f // 18) % 2 == 0 else 0.25) for f in range(BOOT["s2"] + 25, CONTACT, 18)]
reveal(T["S2 Scan"], blink + [(CONTACT, 0.0)], interp="CONSTANT")
type_on(T["S2 Title"], CONTACT + 3, 0.7)
# ARMED: hidden until the lance is charged, then blinks to the end
CHARGED = 500
reveal(T["S3 Armed"], [(F0, 0.0), (CHARGED, 0.0)] + [(f, 1.0 if (f - CHARGED) % 12 < 7 else 0.0) for f in range(CHARGED + 1, F1 + 1)],
       interp="CONSTANT")
# reticle: RANGE label appears with the contact, swaps to LOCK when locked
type_on(T["Holo Reticle Label"], CONTACT + 6, 0.8)
reveal(T["Holo Reticle Label"], ((LOCK - 1, 1.0), (LOCK, 0.0)), interp="CONSTANT")
reveal(T["Holo Reticle Lock"], ((F0, 0.0), (LOCK, 1.0), (LOCK + 2, 0.0), (LOCK + 4, 1.0)), interp="CONSTANT")

# ---------------------------------------------------------------- bars, gauges
def bar_fill(name, x, w, fill0):
    """Returns (scale_x, loc_x) helpers for a fill plane that grows from the track's left edge."""
    o = OB[name]
    left = x - w / 2
    return o, (lambda t: max(t, 0.002) / fill0), (lambda t: left + w * max(t, 0.002) / 2)


# S1 thrust follows the real speed
o, sx, lx = bar_fill("S1 Thrust Fill", 0.0, 0.25, 0.58)
drive(o, "scale", f"max(t, 0.002) / 0.58", 0, t=(hud, '["thrust"]'))
drive(o, "location", f"{-0.125} + 0.25 * max(t, 0.002) / 2", 0, t=(hud, '["thrust"]'))
# S0 reactor bars: boot low, climb with speed, slam to the top on boost
for k, (fill0, idle, cruise) in enumerate(((0.82, 0.35, 0.8), (0.64, 0.28, 0.66), (0.91, 0.4, 0.88))):
    o, sx, lx = bar_fill(f"S0 Bar {k} Fill", 0.01, 0.24, fill0)
    tl = [(F0, 0.0), (BOOT["s0"] + 12 + 3 * k, 0.0), (BOOT["s0"] + 40 + 3 * k, idle), (M2, idle + 0.05),
          (M3, cruise), (M3 + 30 + 4 * k, 0.99), (M4, 0.96)]
    tl += [(f, random.uniform(0.9, 1.0)) for f in range(M4 + 6, F1 + 1, 6)]
    keys(o, "scale", [(f, sx(t)) for f, t in tl], 0)
    keys(o, "location", [(f, lx(t)) for f, t in tl], 0)
# S2 range bar: closes in as the lock builds
o, sx, lx = bar_fill("S2 Range Fill", 0.065, 0.12, 0.4)
tl = [(F0, 0.0), (CONTACT + 10, 0.0), (CONTACT + 30, 0.15), (M3, 0.35), (LOCK, 1.0)]
keys(o, "scale", [(f, sx(t)) for f, t in tl], 0)
keys(o, "location", [(f, lx(t)) for f, t in tl], 0)
# gauge needles swing about the gauge centre with thrust
for sgn in (-1, 1):
    for k, x in enumerate((-0.05, 0.05)):
        n = OB[f"Gauge {sgn}.{k} Needle"]
        piv = OB.new(f"Gauge {sgn}.{k} Pivot", None)
        piv.empty_display_size = 0.01
        coll.objects.link(piv)
        piv.parent = n.parent
        piv.location = (x, -0.011, 0.05)
        mw = n.matrix_world.copy()
        n.parent = piv
        bpy.context.view_layer.update()
        n.matrix_parent_inverse = piv.matrix_world.inverted()
        n.matrix_world = mw
        drive(piv, "rotation_euler", f"t * {1.9 if k else 1.6} - 0.3", 1, t=(hud, '["thrust"]'))

# ---------------------------------------------------------------- S2 contact blip, S3 ion lance charge
blip = OB["S2 Blip"]
keys(blip, "scale", [(F0, (0, 0, 0)), (CONTACT, (0, 0, 0)), (CONTACT + 3, (1.6, 1.6, 1.6)), (CONTACT + 6, (1, 1, 1))])
for f in range(CONTACT + 12, F1 + 1, 10):  # blink
    keys(blip, "scale", ((f, (1, 1, 1)), (f + 5, (0.45, 0.45, 0.45))), interp="CONSTANT")
keys(blip, "location", [(CONTACT, blip.location.copy()), (M3, (-0.06, blip.location.y, blip.location.z - 0.008)),
                        (LOCK, (-0.07, blip.location.y, 0.112))])
glow = OB["S3 Cell 0"].active_material
for k in range(10):
    c = OB[f"S3 Cell {k}"]
    slot = OB.new(f"S3 Cell {k} Slot", c.data.copy())
    coll.objects.link(slot)
    slot.parent, slot.location = c.parent, (c.location.x, c.location.y + 0.0006, c.location.z)
    slot.data.materials[0] = bpy.data.materials["Matte Black"]
    c.data.materials[0] = glow
    on = M3 + 20 + k * 12
    keys(c, "scale", ((F0, (1, 1, 0)), (on, (1, 1, 0)), (on + 2, (1.15, 1, 1.25)), (on + 5, (1, 1, 1))))

# ---------------------------------------------------------------- radar
radar_parts = [OB[n] for n in ("Radar Dome", "Radar Sweep", "Radar Halo")] + [OB[f"Radar Ring {k}"] for k in range(4)] + \
              [OB[f"Radar Blip {k}"] for k in range(4)]
b = BOOT["radar"]
for k, o in enumerate(radar_parts):
    s0 = o.scale.copy()
    rise = (s0.x, s0.y, 0.0) if o.name == "Radar Dome" else (0.0, 0.0, 0.0)
    keys(o, "scale", ((F0, rise), (b + 2 + k, rise), (b + 10 + k, tuple(s0))))
sweep = OB["Radar Sweep"]
ang, z0, pairs = 0.0, sweep.rotation_euler.z, []
for f in range(F0, F1 + 1):
    t = (speed[f] / VMAX) ** 0.6
    ang += math.radians(90 + 900 * t) / FPS  # 90 deg/s cruising -> ~1000 deg/s flat out
    if f % 2 == 1:
        pairs.append((f, z0 + ang))
keys(sweep, "rotation_euler", pairs, 2, interp="LINEAR")
contact_blip = OB["Radar Blip 0"]
for f in range(CONTACT, F1 + 1, 12):
    keys(contact_blip, "scale", ((f, (1.8, 1.8, 1.8)), (f + 4, (1, 1, 1))), interp="LINEAR")

# ---------------------------------------------------------------- holograms
for anchor_name in ("Holo Planet", "Holo Reticle"):
    a = OB[anchor_name]
    b = BOOT["planet" if anchor_name == "Holo Planet" else "reticle"]
    keys(a, "scale", ((F0, (0.01, 0.01, 0.01)), (b, (0.01, 0.01, 0.01)), (b + 5, (1.12, 1.12, 1.12)), (b + 9, (1, 1, 1))))
# planet spins, moon orbits on a pivot
keys(OB["Holo Planet Globe"], "rotation_euler", ((F0, 0.0), (F1, math.radians(25) * (F1 - F0) / FPS)), 2, interp="LINEAR")
moon = OB["Holo Moon"]
orbit = OB.new("Holo Moon Orbit", None)
orbit.empty_display_size = 0.02
coll.objects.link(orbit)
orbit.parent = moon.parent
orbit.rotation_euler = OB["Holo Planet Ring"].rotation_euler
moon.parent = orbit
moon.location = (0.09, 0, 0)
keys(orbit, "rotation_euler", ((F0, 0.0), (F1, math.radians(60) * (F1 - F0) / FPS)), 2, interp="LINEAR")
# reticle: idle drift -> hunting (contact) -> tightening (acceleration) -> lock -> pulse
outer, inner, core = OB["Reticle Outer"], OB["Reticle Inner"], OB["Reticle Core"]
keys(outer, "rotation_euler", ((F0, 0.0), (CONTACT, math.radians(-40)), (M3, math.radians(-200)), (LOCK, math.radians(-270)),
                               (F1, math.radians(-270))), 1)
keys(inner, "rotation_euler", ((F0, 0.0), (CONTACT, math.radians(60)), (M3, math.radians(480)), (LOCK, math.radians(720)),
                               (F1, math.radians(720))), 1)
breath = [(f, (1.15, 1.15, 1.15) if ((f - CONTACT) // 16) % 2 else (1.0, 1.0, 1.0)) for f in range(CONTACT, M3, 16)]
keys(outer, "scale", [(F0, (1, 1, 1))] + breath + [(M3, (1.15, 1.15, 1.15)), (LOCK, (0.72, 0.72, 0.72)), (LOCK + 3, (0.8, 0.8, 0.8))])
keys(core, "scale", [(F0, (1, 1, 1)), (LOCK - 1, (1, 1, 1)), (LOCK + 1, (2.2, 2.2, 2.2)), (LOCK + 6, (1, 1, 1))] +
     [(f + d, (s, s, s)) for f in range(LOCK + 18, F1 + 1, 12) for d, s in ((0, 1.0), (3, 1.5), (8, 1.0))])
keys(hud, '["range_km"]', ((F0, 2.4), (M3, 2.4), (LOCK, 0.6), (F1, 0.35)))
keys(hud, '["p_reticle"]', ((LOCK, 2.6), (LOCK + 8, 1.0)), interp="LINEAR")  # lock flash
# holograms shake with the cockpit turbulence (they're projections; they lag the hull a little)
turb = OB["COCKPIT | Turbulence"]
jn = OB.new("HUD | Holo jitter noise", None)
coll.objects.link(jn)
jn.hide_viewport = jn.hide_render = True
keys(jn, "location", ((F0, (0, 0, 0)),))
for i in range(3):
    m = channelbag(jn).fcurves.find("location", index=i).modifiers.new("NOISE")
    m.scale, m.strength, m.phase = 3.0, 0.004 * 6, 7.0 + i * 13
for anchor_name, sign in (("Holo Planet", 1), ("Holo Reticle", -1)):
    a = OB[anchor_name]
    for i in range(3):
        drive(a, "location", f"{a.location[i]:.5f} + {sign} * n * s * s", i,
              n=(jn, f"location[{i}]"), s=(turb, '["shake"]'))

# ---------------------------------------------------------------- 03 alert, shield
alert = [(F0, 0.0), (M3 + 18, 0.0)] + [(f, 1.0 if ((f - M3) // 10) % 2 == 0 else 0.35) for f in range(M3 + 20, F1 + 1, 10)]
keys(hud, '["alert"]', alert, interp="LINEAR")
keys(hud, '["shield"]', [(F0, 30), (M3 + 40, 30)] + [(f, round(30 - 12 * (f - M3 - 40) / 70)) for f in range(M3 + 44, M3 + 111, 6)],
     interp="CONSTANT")
reveal(T["S2 Shd"], [(f, 1.0 if (f // 6) % 2 == 0 else 0.0) for f in range(M3 + 40, M3 + 112, 6)] + [(M3 + 112, 1.0)],
       interp="CONSTANT")

print("HUD built:", len(T), "text objects;", "G peak", GPEAK)

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
        r.filepath = os.path.join(OUT, "renders", f"hud_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    r.resolution_percentage, r.filepath = saved[0], saved[1]
    if saved[2] is not None:
        r.image_settings.media_type = saved[2]
    r.image_settings.file_format = saved[3]

if arg("--save"):
    scene.frame_set(F0)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, arg("--save")), copy=True)
    print("SAVED", arg("--save"))

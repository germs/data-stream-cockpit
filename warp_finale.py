"""Warp-jump finale: extend the shot to 30 s (720 frames). We hold the lock, never fire, and jump away.

  560  05 | Jump spool   ION LANCE -> JUMP DRIVE, countdown T-5..T-0, cells refill, vibration builds, stars appear
  ~589-610              KESTREL-9 cameo: it circles back and lunges at the canopy, jaws wide
  610  06 | Jump        the punch: stars snap to streaks, white flash, G-kick, lens punch, terrain gone, KESTREL left behind
  612  07 | Hyperspace  blue-white streak tunnel, cockpit washed in flickering blue, HUD tinted, turbulence settles to a hum
  660  08 | Exit        streaks stretch and converge to a bright core, white-out
  684  09 | Title       cut (inside the white) to the title card, which resolves out of the white
  720  10 | End - 30 seconds

Everything renders without Python: the warp is Geometry Nodes driven by props on `WARP | Control`
(travel, stretch, bright, core); the flash and zoom blur are keyed compositor inputs; the title is a marker-bound camera.

Run on the creature file:
  Blender --background data_stream_cockpit_kestrel.blend --python warp_finale.py -- \
      [--render 590,606,611,630,676,700] [--percent 50] [--save NAME.blend]
"""
import bpy, math, os, sys
from mathutils import Vector
from bpy_extras import anim_utils

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


scene = bpy.context.scene
OB = bpy.data.objects
D = math.radians
SPOOL, JUMP, HYPER, EXIT, TITLE, END = 560, 610, 612, 660, 684, 720
if "WARP | Control" in OB:
    sys.exit("warp_finale: already applied to this file")

cam = OB["Low flight camera"]
rig = OB["COCKPIT | Rig"]
body = OB["COCKPIT | Body"]
hud = OB["HUD | Control"]
cockpit = bpy.data.collections["COCKPIT"]


# ---------------------------------------------------------------- helpers
def channelbag(idb):
    ad = idb.animation_data
    return anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)


def fcurve(idb, path, index=0):
    return channelbag(idb).fcurves.find(path, index=index)


def setv(idb, path, value, index=-1):
    if path.startswith('["'):
        idb[path[2:-2]] = value
    elif "." in path:
        owner, attr = path.rsplit(".", 1)
        setattr(idb.path_resolve(owner), attr, value)
    elif index >= 0:
        getattr(idb, path)[index] = value
    else:
        setattr(idb, path, value)


def keys(idb, path, pairs, index=-1, interp="BEZIER"):
    for f, v in pairs:
        setv(idb, path, v, index)
        idb.keyframe_insert(path, index=index, frame=f)
        n = len(v) if isinstance(v, (tuple, list, Vector)) else 1
        for i in (range(n) if index < 0 and n > 1 else [max(index, 0)]):
            fc = channelbag(idb).fcurves.find(path, index=i)
            for kp in fc.keyframe_points:
                if abs(kp.co.x - f) < 0.01:
                    kp.interpolation = interp


def clear_after(idb, path, frame, index=0):
    fc = fcurve(idb, path, index)
    if fc:
        for kp in reversed(list(fc.keyframe_points)):
            if kp.co.x > frame:
                fc.keyframe_points.remove(kp)


def drive(owner, path, expr, index=-1, **vars_):
    d = (owner.driver_add(path, index) if index >= 0 else owner.driver_add(path)).driver
    d.type = "SCRIPTED"
    for name, (idb, dp) in vars_.items():
        v = d.variables.new()
        v.name = name
        v.targets[0].id = idb
        v.targets[0].data_path = dp
    d.expression = expr


def empty(name, coll, parent=None, loc=(0, 0, 0)):
    e = OB.new(name, None)
    e.empty_display_size = 0.3
    coll.objects.link(e)
    e.parent, e.location = parent, loc
    return e


# ---------------------------------------------------------------- timeline
scene.frame_end = END
mk = {m.name: m for m in scene.timeline_markers}
mk["01 | Slow glide"].camera = cam  # with a camera-bound title marker, frame 1 must bind the cockpit camera back
old_end = next(m for m in scene.timeline_markers if m.name.startswith("05"))
old_end.name, old_end.frame = "05 | Jump spool", SPOOL
for name, f in (("06 | Jump", JUMP), ("07 | Hyperspace", HYPER), ("08 | Exit", EXIT), ("10 | End - 30 seconds", END)):
    scene.timeline_markers.new(name, frame=f)

# terrain keeps rushing until the jump. The 25 s cut braked to a stop at 600 (a flat last key); now the ship holds
# its top speed (~40 m/frame, 960 m/s) from 552 straight into the jump, with the speed continuous at 552.
trav = fcurve(OB["SPEED CONTROL"], '["travel"]')
V = 40.0
kp = {round(k.co.x): k for k in trav.keyframe_points}
k552, k600 = kp[552], kp[600]
k600.co.y = k552.co.y + V * (600 - 552)
k552.interpolation = k600.interpolation = "LINEAR"
k552.handle_left_type = "ALIGNED"
k552.handle_left = (552 - 16, k552.co.y - 16 * V)
k552.handle_right_type = "ALIGNED"
k552.handle_right = (552 + 16, k552.co.y + 16 * V)
nk = trav.keyframe_points.insert(JUMP + 1, k600.co.y + V * (JUMP + 1 - 600))
nk.interpolation = "LINEAR"
trav.update()

# ---------------------------------------------------------------- the world falls away at the jump
FX = ("COCKPIT", "KESTREL", "WARP", "TITLE")
world_objs = [o for o in OB if o.type in ("MESH", "CURVE", "FONT")
              and not any(c.name.startswith(FX) for c in o.users_collection)]
for o in world_objs:
    keys(o, "hide_render", [(JUMP, o.hide_render), (JUMP + 1, True)], interp="CONSTANT")
keys(cam.data, "clip_end", [(JUMP, cam.data.clip_end), (JUMP + 1, 3000.0)], interp="CONSTANT")

# ---------------------------------------------------------------- warp field
wcoll = bpy.data.collections.new("WARP")
scene.collection.children.link(wcoll)
parts = bpy.data.collections.new("WARP | Parts (instanced)")
wcoll.children.link(parts)
ctl = empty("WARP | Control", wcoll, rig, (0, 0.6, 1.6))
ctl.hide_render = True
for p, v in (("travel", 0.0), ("stretch", 0.4), ("bright", 0.0), ("core", 0.0)):
    ctl[p] = v

# streak material: additive, bright head fading down the tail, colour picked per streak from "tint"
sm = bpy.data.materials.new("WARP Streak")
nt = sm.node_tree
nt.nodes.clear()
N, L = nt.nodes, nt.links
uv = N.new("ShaderNodeUVMap")
sep = N.new("ShaderNodeSeparateXYZ")
L.new(uv.outputs[0], sep.inputs[0])
fade = N.new("ShaderNodeMath"); fade.operation = "POWER"
inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0
L.new(sep.outputs["Y"], inv.inputs[1])
L.new(inv.outputs[0], fade.inputs[0]); fade.inputs[1].default_value = 2.2
attr = N.new("ShaderNodeAttribute"); attr.attribute_type = "INSTANCER"; attr.attribute_name = "tint"
ramp = N.new("ShaderNodeValToRGB")
cr = ramp.color_ramp
cr.elements[0].position, cr.elements[0].color = 0.0, (0.25, 0.5, 1.0, 1)
cr.elements[1].position, cr.elements[1].color = 0.62, (0.55, 0.8, 1.0, 1)
for pos, col in ((0.8, (1.0, 1.0, 1.0, 1)), (0.93, (1.0, 0.75, 0.4, 1))):
    e = cr.elements.new(pos); e.color = col
cr.interpolation = "CONSTANT"
L.new(attr.outputs["Fac"], ramp.inputs[0])
bright = N.new("ShaderNodeValue")
drive(bright.outputs[0], "default_value", "b * 4", b=(ctl, '["bright"]'))
mul = N.new("ShaderNodeMath"); mul.operation = "MULTIPLY"
L.new(fade.outputs[0], mul.inputs[0]); L.new(bright.outputs[0], mul.inputs[1])
em = N.new("ShaderNodeEmission")
L.new(ramp.outputs[0], em.inputs["Color"]); L.new(mul.outputs[0], em.inputs["Strength"])
tr = N.new("ShaderNodeBsdfTransparent")
add = N.new("ShaderNodeAddShader")
L.new(tr.outputs[0], add.inputs[0]); L.new(em.outputs[0], add.inputs[1])
out = N.new("ShaderNodeOutputMaterial")
L.new(add.outputs[0], out.inputs[0])
sm.surface_render_method = "BLENDED"

# unit streak: two crossed ribbons, y 0 (head) .. 1 (tail), uv.y along the length
me = bpy.data.meshes.new("WARP Streak unit")
me.from_pydata([(-0.5, 0, 0), (0.5, 0, 0), (0.5, 1, 0), (-0.5, 1, 0), (0, 0, -0.5), (0, 0, 0.5), (0, 1, 0.5), (0, 1, -0.5)],
               [], [(0, 1, 2, 3), (4, 5, 6, 7)])
uvl = me.uv_layers.new()
for poly in me.polygons:
    for li in poly.loop_indices:
        v = me.vertices[me.loops[li].vertex_index].co
        uvl.data[li].uv = (0.5, v.y)
me.materials.append(sm)
unit = OB.new("WARP | Streak unit", me)
parts.objects.link(unit)


def exclude(lc):  # the source streak sits at the origin; only its instances should render
    for c in lc.children:
        if c.collection == parts:
            c.exclude = True
        exclude(c)


for vl in scene.view_layers:
    exclude(vl.layer_collection)

DEPTH, COUNT = 1600.0, 6000
g = bpy.data.node_groups.new("WARP Streaks", "GeometryNodeTree")
g.is_modifier = True
ids = {}
for nm in ("Travel", "Stretch"):
    ids[nm] = g.interface.new_socket(nm, in_out="INPUT", socket_type="NodeSocketFloat").identifier
g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
GN, GL = g.nodes, g.links
gi = GN.new("NodeGroupInput")


def rnd(lo, hi, seed):
    r = GN.new("FunctionNodeRandomValue"); r.data_type = "FLOAT"
    r.inputs["Seed"].default_value = seed
    next(s for s in r.inputs if s.name == "Min" and s.type == "VALUE").default_value = lo
    next(s for s in r.inputs if s.name == "Max" and s.type == "VALUE").default_value = hi
    return next(s for s in r.outputs if s.type == "VALUE")


def m(op, a, b=None):
    n = GN.new("ShaderNodeMath"); n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            GL.new(v, n.inputs[i])
    return n.outputs[0]


theta = rnd(0.0, 2 * math.pi, 11)
rad = m("ADD", m("MULTIPLY", m("POWER", rnd(0.0, 1.0, 12), 1.6), 170.0), 7.0)
y = m("SUBTRACT", m("FLOORED_MODULO", m("SUBTRACT", rnd(0.0, DEPTH, 13), gi.outputs["Travel"]), DEPTH), 40.0)
pos = GN.new("ShaderNodeCombineXYZ")
GL.new(m("MULTIPLY", rad, m("COSINE", theta)), pos.inputs["X"])
GL.new(y, pos.inputs["Y"])
GL.new(m("MULTIPLY", rad, m("SINE", theta)), pos.inputs["Z"])
pts = GN.new("GeometryNodePoints")
pts.inputs["Count"].default_value = COUNT
GL.new(pos.outputs[0], pts.inputs["Position"])
store = GN.new("GeometryNodeStoreNamedAttribute"); store.data_type = "FLOAT"; store.domain = "POINT"
GL.new(pts.outputs[0], store.inputs["Geometry"])
store.inputs["Name"].default_value = "tint"
GL.new(rnd(0.0, 1.0, 14), next(s for s in store.inputs if s.name == "Value" and s.type == "VALUE"))
oi = GN.new("GeometryNodeObjectInfo")
oi.inputs["Object"].default_value = unit
iop = GN.new("GeometryNodeInstanceOnPoints")
GL.new(store.outputs[0], iop.inputs["Points"])
GL.new(oi.outputs["Geometry"], iop.inputs["Instance"])
# streaks thin to nothing at both ends of the tunnel, so the wrap (behind the camera -> far end) never shows,
# not even as a motion-blur smear
def ramp01(val, a, b):
    mr = GN.new("ShaderNodeMapRange"); mr.clamp = True
    GL.new(val, mr.inputs["Value"])
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = a, b
    return mr.outputs[0]


edge = m("MULTIPLY", ramp01(y, -40.0, -10.0), ramp01(y, DEPTH - 40.0, DEPTH - 340.0))
w = m("MULTIPLY", m("ADD", 0.03, m("MULTIPLY", rad, 0.002)), edge)
sc = GN.new("ShaderNodeCombineXYZ")
GL.new(w, sc.inputs["X"]); GL.new(gi.outputs["Stretch"], sc.inputs["Y"]); GL.new(w, sc.inputs["Z"])
GL.new(sc.outputs[0], iop.inputs["Scale"])
go = GN.new("NodeGroupOutput")
GL.new(iop.outputs[0], go.inputs[0])

streaks = OB.new("WARP | Streaks", bpy.data.meshes.new("WARP Streaks"))
wcoll.objects.link(streaks)
streaks.parent = body  # centred on the pilot's eye, banks with the ship, doesn't shake (the camera does)
mod = streaks.modifiers.new("Warp", "NODES")
mod.node_group = g
for nm, prop in (("Travel", "travel"), ("Stretch", "stretch")):
    drive(streaks, f'modifiers["Warp"].properties.inputs.{ids[nm]}.value', "v", v=(ctl, f'["{prop}"]'))

# bright core far down the tunnel
core_me = bpy.data.meshes.new("WARP Core")
core_me.from_pydata([(-0.5, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (-0.5, 0, 0.5)], [], [(0, 1, 2, 3)])
cuv = core_me.uv_layers.new()
for li, co in zip(range(4), ((0, 0), (1, 0), (1, 1), (0, 1))):
    cuv.data[li].uv = co
cm = bpy.data.materials.new("WARP Core glow")
cn = cm.node_tree
cn.nodes.clear()
tc = cn.nodes.new("ShaderNodeTexCoord")
mp = cn.nodes.new("ShaderNodeMapping"); mp.vector_type = "TEXTURE"
mp.inputs["Location"].default_value = (0.5, 0.5, 0); mp.inputs["Scale"].default_value = (0.5, 0.5, 1)
gr = cn.nodes.new("ShaderNodeTexGradient"); gr.gradient_type = "SPHERICAL"
pw = cn.nodes.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = 3.0
cv = cn.nodes.new("ShaderNodeValue")
drive(cv.outputs[0], "default_value", "c * 10", c=(ctl, '["core"]'))
cmul = cn.nodes.new("ShaderNodeMath"); cmul.operation = "MULTIPLY"
cem = cn.nodes.new("ShaderNodeEmission"); cem.inputs["Color"].default_value = (0.75, 0.88, 1.0, 1)
ctr, cadd, cout = cn.nodes.new("ShaderNodeBsdfTransparent"), cn.nodes.new("ShaderNodeAddShader"), cn.nodes.new("ShaderNodeOutputMaterial")
cn.links.new(tc.outputs["UV"], mp.inputs["Vector"]); cn.links.new(mp.outputs[0], gr.inputs["Vector"])
cn.links.new(gr.outputs["Fac"], pw.inputs[0]); cn.links.new(pw.outputs[0], cmul.inputs[0]); cn.links.new(cv.outputs[0], cmul.inputs[1])
cn.links.new(cmul.outputs[0], cem.inputs["Strength"]); cn.links.new(ctr.outputs[0], cadd.inputs[0]); cn.links.new(cem.outputs[0], cadd.inputs[1])
cn.links.new(cadd.outputs[0], cout.inputs[0])
cm.surface_render_method = "BLENDED"
core_me.materials.append(cm)
core = OB.new("WARP | Core", core_me)
wcoll.objects.link(core)
core.parent, core.location, core.scale = body, (0, 1400, 0), (600, 1, 600)

# blue light washing the cockpit
wl = bpy.data.lights.new("WARP Light", "POINT")
wl.color, wl.shadow_soft_size, wl.energy = (0.5, 0.75, 1.0), 0.6, 0.0
wlo = OB.new("WARP | Light", wl)
wcoll.objects.link(wlo)
wlo.parent, wlo.location = rig, (0, 1.9, 1.5)

for o in (streaks, core):
    keys(o, "scale", [(1, tuple(v * 0.0001 for v in o.scale)), (584, tuple(v * 0.0001 for v in o.scale)),
                      (585, tuple(o.scale)), (TITLE - 1, tuple(o.scale)), (TITLE, tuple(v * 0.0001 for v in o.scale))],
         interp="CONSTANT")
keys(ctl, '["bright"]', [(1, 0.0), (585, 0.0), (600, 0.5), (JUMP - 1, 0.8), (JUMP + 1, 3.0), (JUMP + 6, 1.3), (EXIT, 1.4),
                         (EXIT + 16, 4.0), (TITLE, 4.0)])
keys(ctl, '["stretch"]', [(1, 0.4), (598, 0.4), (JUMP - 1, 8.0), (JUMP + 1, 160.0), (JUMP + 10, 220.0), (EXIT, 240.0),
                          (EXIT + 16, 700.0)])
keys(ctl, '["travel"]', [(1, 0.0), (585, 0.0), (JUMP - 1, 150.0)], interp="BEZIER")
keys(ctl, '["travel"]', [(JUMP + 1, 450.0), (EXIT, 450.0 + 130 * (EXIT - JUMP - 1)), (EXIT + 16, 450.0 + 130 * (EXIT - JUMP - 1) + 16 * 260)],
     interp="LINEAR")
keys(ctl, '["core"]', [(1, 0.0), (JUMP, 0.0), (JUMP + 2, 0.6), (EXIT, 0.8), (EXIT + 16, 8.0)])
keys(wl, "energy", [(1, 0.0), (JUMP, 0.0), (JUMP + 1, 2500.0), (JUMP + 6, 350.0), (EXIT, 400.0), (EXIT + 16, 2000.0)])
wfc = fcurve(wl, "energy")
nm_ = wfc.modifiers.new("NOISE")
nm_.scale, nm_.strength, nm_.phase = 2.0, 240.0, 3.0
nm_.use_restricted_range, nm_.frame_start, nm_.frame_end = True, JUMP + 2, TITLE

# ---------------------------------------------------------------- the jump: G-kick, lens punch, turbulence
for idx, peak, mid, low in ((2, 0.16, 0.08, 0.04), (0, D(3.5), D(1.5), D(0.8))):
    path = "location" if idx == 2 else "rotation_euler"
    base = fcurve(cam, path, idx).evaluate(JUMP - 1)
    keys(cam, path, [(JUMP - 1, base), (JUMP + 1, base + peak), (JUMP + 6, base + mid), (JUMP + 20, base + low), (END, base + low)], index=idx)
lens = fcurve(cam.data, "lens").evaluate(JUMP - 1)
keys(cam.data, "lens", [(JUMP - 1, lens), (JUMP + 2, lens * 1.5), (JUMP + 20, lens * 1.2), (EXIT, lens * 1.15), (EXIT + 16, lens * 0.85)])
turb = OB["COCKPIT | Turbulence"]
keys(turb, '["shake"]', [(SPOOL, 1.0), (JUMP - 5, 2.2), (JUMP, 2.6), (JUMP + 2, 3.2), (JUMP + 8, 0.35), (END, 0.35)])

# ---------------------------------------------------------------- HUD: jump drive, countdown, blue tint
hud["jump"] = 0.0
hud["countdown"] = 5.0
hud.update_tag()  # new ID props must reach the evaluated copy, or keys and drivers on them silently do nothing
bpy.context.view_layer.update()
BLUE = (0.25, 0.62, 1.0, 1)
for mat in bpy.data.materials:
    if " | " not in mat.name or mat.name.split(" | ")[-1] not in ("s0", "s1", "s2", "s3", "radar", "planet", "reticle"):
        continue
    mnt = mat.node_tree
    emn = next((n for n in mnt.nodes if n.bl_idname in ("ShaderNodeEmission", "ShaderNodeBsdfPrincipled")), None)
    if emn is None:
        continue
    cs = emn.inputs["Color" if emn.bl_idname == "ShaderNodeEmission" else "Emission Color"]
    mix = mnt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    a = next(s for s in mix.inputs if s.name == "A" and s.type == "RGBA")
    b = next(s for s in mix.inputs if s.name == "B" and s.type == "RGBA")
    if cs.is_linked:
        mnt.links.new(cs.links[0].from_socket, a)
    else:
        a.default_value = cs.default_value
    b.default_value = BLUE
    drive(next(s for s in mix.inputs if s.name == "Factor" and s.type == "VALUE"), "default_value", "j", j=(hud, '["jump"]'))
    mnt.links.new(next(s for s in mix.outputs if s.name == "Result" and s.type == "RGBA"), cs)
keys(hud, '["jump"]', [(1, 0.0), (SPOOL, 0.0), (JUMP - 1, 0.45), (JUMP + 1, 1.0), (END, 0.85)])
keys(hud, '["alert"]', [(JUMP, 1.0), (JUMP + 1, 0.0)], interp="CONSTANT")
# re-bake the velocity readout from the extended travel curve (the old flat end made it sag toward 600)
clear_after(hud, '["speed"]', SPOOL - 1)
clear_after(hud, '["thrust"]', SPOOL - 1)
keys(hud, '["speed"]', [(f, round((trav.evaluate(f + 0.5) - trav.evaluate(f - 0.5)) * scene.render.fps)) for f in range(SPOOL, JUMP + 1, 2)]
     + [(JUMP + 1, 99999.0)], interp="CONSTANT")
keys(hud, '["thrust"]', [(SPOOL, 1.0), (JUMP + 1, 1.0)], interp="CONSTANT")
for g_ in ("s0", "s1", "s2", "s3"):
    keys(hud, f'["p_{g_}"]', [(JUMP + 1, 1.8), (JUMP + 2, 0.3), (JUMP + 4, 1.2), (JUMP + 6, 1.0)], interp="CONSTANT")
keys(hud, '["p_reticle"]', [(JUMP, 1.0), (JUMP + 1, 0.4), (JUMP + 3, 0.9), (JUMP + 5, 0.15), (JUMP + 9, 0.0)], interp="CONSTANT")

ht = bpy.data.node_groups["HUD Text"]
SID = {i.name: i.identifier for i in ht.interface.items_tree if getattr(i, "in_out", "") == "INPUT"}


def ipath(sock):
    return f'modifiers["HUD Text"].properties.inputs.{SID[sock]}.value'


def clone_text(src_name, name, text, loc=None):
    src = OB[src_name]
    o = src.copy()
    o.data = src.data.copy()
    o.animation_data_clear()
    o.name = name
    for c in src.users_collection:
        c.objects.link(o)
    if loc:
        o.location = loc
    setv(o, ipath("Text"), text)
    setv(o, ipath("Use Number"), False)
    return o


def reveal(o, pairs):
    keys(o, ipath("Reveal"), pairs, interp="CONSTANT")


s3t, armed = OB["S3 Title"], OB["S3 Armed"]
jump_t = clone_text("S3 Title", "S3 Jump", "JUMP DRIVE")
count_t = clone_text("S3 Armed", "S3 Count", "")
setv(count_t, ipath("Use Number"), True)
setv(count_t, ipath("Prefix"), "T-")
setv(count_t, ipath("Decimals"), 0)
drive(count_t, ipath("Number"), "v", v=(hud, '["countdown"]'))
engaged = clone_text("S3 Armed", "S3 Engaged", "ENGAGED")
reveal(s3t, [(SPOOL, 1.0), (SPOOL + 1, 0.0), (SPOOL + 3, 1.0), (SPOOL + 4, 0.0)])
reveal(jump_t, [(1, 0.0), (SPOOL + 1, 1.0), (SPOOL + 3, 0.0), (SPOOL + 4, 1.0)])
clear_after(armed, ipath("Reveal"), SPOOL)
reveal(armed, [(SPOOL, 0.0)])
reveal(count_t, [(1, 0.0), (SPOOL + 2, 1.0), (JUMP + 1, 0.0)])
reveal(engaged, [(1, 0.0)] + [(f, 1.0 if (f - JUMP) % 8 < 5 else 0.0) for f in range(JUMP + 1, END + 1, 2)])
keys(hud, '["countdown"]', [(1, 5.0), (SPOOL + 2, 5.0), (572, 4.0), (582, 3.0), (592, 2.0), (601, 1.0), (JUMP, 0.0)], interp="CONSTANT")
for k in range(10):
    c = OB[f"S3 Cell {k}"]
    refill = SPOOL + 6 + k * 4
    keys(c, "scale", [(SPOOL + 1, (1, 1, 1)), (SPOOL + 4, (1, 1, 0)), (refill, (1, 1, 0)), (refill + 2, (1.15, 1, 1.25)),
                      (refill + 4, (1, 1, 1))])
for lbl in ("Holo Reticle Lock",):
    clear_after(OB[lbl], ipath("Reveal"), JUMP)
    reveal(OB[lbl], [(JUMP + 1, 0.0)])

# ---------------------------------------------------------------- KESTREL-9 cameo: it circles back and lunges
fl, head = OB["KESTREL | Flight"], OB["KESTREL | Head"]
CAMEO = [  # camera space: x right, y up, z back (negative = ahead); yaw 180 = facing us
    (589, (55, 12, -320), 205), (598, (30, 8, -120), 200), (604, (12, 4, -45), 195),
    (608, (6, 2.5, -20), 190), (JUMP, (4, 1.6, -12), 186),
    (JUMP + 1, (4, 1.6, 40), 186), (JUMP + 2, (4, 1.6, 400), 186),  # we jump; it is gone behind us
]
for f, loc, yaw in CAMEO:
    scene.frame_set(f)
    keys(fl, "location", [(f, tuple(cam.matrix_world @ Vector(loc)))], interp="LINEAR" if f >= JUMP else "BEZIER")
    keys(fl, "rotation_euler", [(f, D(yaw))], index=2)
keys(fl, "rotation_euler", [(589, 0.0), (604, D(-10)), (JUMP, D(-14))], index=0)
keys(fl, "scale", [(588, (0.0001,) * 3), (589, (1.0,) * 3), (JUMP + 2, (1.0,) * 3), (JUMP + 3, (0.0001,) * 3)], interp="CONSTANT")
keys(head, '["hood"]', [(590, 0.0), (600, 1.1), (604, 1.0)])
keys(head, '["jaw"]', [(598, 0.0), (606, 1.0)])
keys(head, '["tongue"]', [(600, 0.0)] + [(f, 1.0 if (f // 3) % 2 == 0 else 0.1) for f in range(602, JUMP + 1, 3)], interp="LINEAR")
eye = OB["KESTREL | Eye light"].data
keys(eye, "energy", [(596, 250.0), (606, 9000.0), (JUMP, 9000.0), (JUMP + 1, 0.0)])

# ---------------------------------------------------------------- compositor: zoom blur + flash / white-out
cg = scene.compositing_node_group
glare = next(n for n in cg.nodes if n.bl_idname == "CompositorNodeGlare")
gout = next(n for n in cg.nodes if n.bl_idname == "NodeGroupOutput")
zb = cg.nodes.new("CompositorNodeDBlur")
zb.inputs["Samples"].default_value = 12
zb.inputs["Scale"].default_value = 1.0
ex = cg.nodes.new("CompositorNodeExposure")
zb.location, ex.location = glare.location + Vector((250, 0)), glare.location + Vector((500, 0))
gout.location = glare.location + Vector((750, 0))
for l in list(cg.links):
    if l.to_node == gout:
        cg.links.remove(l)
cg.links.new(glare.outputs["Image"], zb.inputs["Image"])
cg.links.new(zb.outputs[0], ex.inputs["Image"])
cg.links.new(ex.outputs[0], gout.inputs[0])
zs, es = zb.inputs["Scale"], ex.inputs["Exposure"]
# zoom blur only on the punch and the exit, so the cockpit stays crisp in hyperspace
for f, v in ((1, 1.0), (JUMP - 1, 1.0), (JUMP + 1, 1.25), (JUMP + 6, 1.0), (EXIT, 1.0), (EXIT + 16, 1.15), (TITLE - 1, 1.15), (TITLE, 1.0)):
    zs.default_value = v
    zs.keyframe_insert("default_value", frame=f)
for f, v in ((1, 0.0), (JUMP, 0.0), (JUMP + 1, 2.0), (JUMP + 3, 0.5), (JUMP + 6, 0.0), (EXIT, 0.0), (EXIT + 16, 7.0),
             (TITLE, 7.0), (TITLE + 16, 0.0)):
    es.default_value = v
    es.keyframe_insert("default_value", frame=f)
zs.default_value, es.default_value = 1.0, 0.0

# ---------------------------------------------------------------- title card, far below the world
tcoll = bpy.data.collections.new("TITLE")
scene.collection.children.link(tcoll)
T0 = Vector((0, 0, -5000))
font = bpy.data.fonts.get("DIN Condensed Bold")  # the cockpit's packed HUD font


def title_text(name, body_txt, size, z, color, strength):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body, cu.size, cu.align_x, cu.align_y = body_txt, size, "CENTER", "CENTER"
    if font:
        cu.font = font
    mt = bpy.data.materials.new(name + " glow")
    mt.node_tree.nodes.clear()
    e = mt.node_tree.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value, e.inputs["Strength"].default_value = color, strength
    o_ = mt.node_tree.nodes.new("ShaderNodeOutputMaterial")
    mt.node_tree.links.new(e.outputs[0], o_.inputs[0])
    cu.materials.append(mt)
    o = OB.new(name, cu)
    tcoll.objects.link(o)
    o.location, o.rotation_euler = T0 + Vector((0, 0, z)), (D(90), 0, 0)
    return o


title_text("TITLE | Main", "DATA STREAM", 1.0, 0.25, (0.75, 0.9, 1.0, 1), 6.0)
title_text("TITLE | Sub", "KESTREL-9   //   CONTACT LOST", 0.2, -0.55, (0.3, 0.75, 1.0, 1), 3.0)
bd = bpy.data.meshes.new("TITLE Backdrop")
bd.from_pydata([(-200, 0, -200), (200, 0, -200), (200, 0, 200), (-200, 0, 200)], [], [(0, 1, 2, 3)])
bdm = bpy.data.materials.new("TITLE Black")
bdm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0, 0, 0, 1)
bdm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
bd.materials.append(bdm)
bdo = OB.new("TITLE | Backdrop", bd)
tcoll.objects.link(bdo)
bdo.location = T0 + Vector((0, 30, 0))
tcd = bpy.data.cameras.new("TITLE Camera")
tcd.lens, tcd.clip_end = 50, 200
tco = OB.new("TITLE | Camera", tcd)
tcoll.objects.link(tco)
tco.rotation_euler = (D(90), 0, 0)
keys(tco, "location", [(TITLE, tuple(T0 + Vector((0, -11, 0)))), (END, tuple(T0 + Vector((0, -9.6, 0))))], interp="LINEAR")
scene.timeline_markers.new("09 | Title", frame=TITLE).camera = tco

print("WARP FINALE built: frames", scene.frame_start, "-", scene.frame_end, "| world objects hidden at jump:", len(world_objs))

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
        r.filepath = os.path.join(OUT, "renders", f"finale_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    r.resolution_percentage, r.filepath = saved[0], saved[1]
    if saved[2] is not None:
        r.image_settings.media_type = saved[2]
    r.image_settings.file_format = saved[3]

if arg("--save"):
    scene.frame_set(scene.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, arg("--save")), copy=True)
    print("SAVED", arg("--save"))

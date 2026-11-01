"""Procedural spaceship cockpit dash for Blender 5.x.

Run headless:
  Blender --background --factory-startup --python cockpit_dash.py -- [--render] [--save]

Pilot sits at the origin looking down +Y; X is right, Z is up (metres).
"""
import bpy, bmesh, math, os, sys, random
from mathutils import Vector

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
random.seed(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = scene.collection

AMBER = (1.0, 0.42, 0.06)
RED = (1.0, 0.12, 0.05)
CYAN = (0.1, 0.85, 1.0)
GREEN = (0.25, 1.0, 0.3)


# ---------------------------------------------------------------- materials
def _nodes(m):
    try:
        m.use_nodes = True
    except Exception:
        pass
    return m.node_tree.nodes, m.node_tree.links


def mat_surface(name, color, metallic=0.0, rough=0.5, emit=None, strength=0.0):
    m = bpy.data.materials.new(name)
    nodes, _ = _nodes(m)
    b = nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


def mat_glow(name, color, strength):
    """Pure emissive material for light strips, text and buttons."""
    m = bpy.data.materials.new(name)
    nodes, links = _nodes(m)
    nodes.clear()
    e = nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    o = nodes.new("ShaderNodeOutputMaterial")
    links.new(e.outputs[0], o.inputs[0])
    return m


def mat_holo(name, color, strength, radial=False):
    """Additive see-through emission; radial=True fades out from the centre (glow halos)."""
    m = bpy.data.materials.new(name)
    nodes, links = _nodes(m)
    nodes.clear()
    e = nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    t = nodes.new("ShaderNodeBsdfTransparent")
    add = nodes.new("ShaderNodeAddShader")
    o = nodes.new("ShaderNodeOutputMaterial")
    if radial:
        tc = nodes.new("ShaderNodeTexCoord")
        g = nodes.new("ShaderNodeTexGradient")
        g.gradient_type = "SPHERICAL"
        mp = nodes.new("ShaderNodeMapping")
        mp.vector_type = "TEXTURE"
        mp.inputs["Location"].default_value = (0.5, 0.5, 0)
        mp.inputs["Scale"].default_value = (0.5, 0.5, 1)
        pw = nodes.new("ShaderNodeMath")
        pw.operation = "POWER"
        pw.inputs[1].default_value = 2.0
        mul = nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = strength
        links.new(tc.outputs["UV"], mp.inputs["Vector"])
        links.new(mp.outputs[0], g.inputs["Vector"])
        links.new(g.outputs["Fac"], pw.inputs[0])
        links.new(pw.outputs[0], mul.inputs[0])
        links.new(mul.outputs[0], e.inputs["Strength"])
    links.new(t.outputs[0], add.inputs[0])
    links.new(e.outputs[0], add.inputs[1])
    links.new(add.outputs[0], o.inputs[0])
    m.surface_render_method = "BLENDED"
    return m


def mat_screen(name, color):
    """Dark tinted display glass with faint scanlines."""
    m = bpy.data.materials.new(name)
    nodes, links = _nodes(m)
    b = nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.005, 0.005, 0.006, 1)
    b.inputs["Roughness"].default_value = 0.15
    b.inputs["Emission Color"].default_value = (*color, 1)
    tc = nodes.new("ShaderNodeTexCoord")
    w = nodes.new("ShaderNodeTexWave")
    w.wave_type = "BANDS"
    w.bands_direction = "Y"
    w.inputs["Scale"].default_value = 60
    w.inputs["Distortion"].default_value = 0
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = 0.08
    ramp.inputs["To Max"].default_value = 0.22
    links.new(tc.outputs["UV"], w.inputs["Vector"])
    links.new(w.outputs["Fac"], ramp.inputs["Value"])
    links.new(ramp.outputs[0], b.inputs["Emission Strength"])
    return m


M_HULL = mat_surface("Hull Graphite", (0.03, 0.032, 0.036), metallic=0.55, rough=0.42)
M_DARK = mat_surface("Matte Black", (0.012, 0.012, 0.014), metallic=0.2, rough=0.6)
M_TRIM = mat_surface("Burnished Copper", (0.45, 0.17, 0.07), metallic=1.0, rough=0.32)
M_RUBBER = mat_surface("Rubber", (0.02, 0.02, 0.02), rough=0.85)
G_AMBER = mat_glow("Glow Amber", AMBER, 9)
G_AMBER_SOFT = mat_glow("Glow Amber Soft", AMBER, 3)
G_STRIP = mat_glow("Strip Amber", AMBER, 4)
G_STRIP_RED = mat_glow("Strip Red", RED, 5)
G_STRIP_CYAN = mat_glow("Strip Cyan", CYAN, 3)
G_RED = mat_glow("Glow Red", RED, 10)
G_CYAN = mat_glow("Glow Cyan", CYAN, 7)
G_GREEN = mat_glow("Glow Green", GREEN, 8)
G_WHITE = mat_glow("Glow White", (1, 0.85, 0.7), 6)
H_AMBER = mat_holo("Holo Amber", AMBER, 5)
H_CYAN = mat_holo("Holo Cyan", CYAN, 4)
HALO_AMBER = mat_holo("Halo Amber", (1.0, 0.25, 0.04), 2.5, radial=True)
HALO_CYAN = mat_holo("Halo Cyan", (0.1, 0.5, 1.0), 2.0, radial=True)


# ---------------------------------------------------------------- geometry helpers
def link(name, me, material=None, parent=None, loc=(0, 0, 0), rot=(0, 0, 0)):
    o = bpy.data.objects.new(name, me)
    COL.objects.link(o)
    if material:
        me.materials.append(material)
    o.parent = parent
    o.location = loc
    o.rotation_euler = rot
    return o


def mesh(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return me


def bevel(o, width=0.004, segments=2, angle=40):
    m = o.modifiers.new("Bevel", "BEVEL")
    m.width = width
    m.segments = segments
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(angle)
    m.harden_normals = True
    o.data.shade_smooth()
    return o


def smooth_sharp(o, angle=35):
    o.data.shade_smooth()
    o.data.set_sharp_from_angle(angle=math.radians(angle))
    return o


def sweep(name, pts, sides, ups, profile, material, cap=True, parent=None):
    """Extrude a closed 2D profile (side, up) along a path with per-point frames."""
    n = len(profile)
    verts = [p + s * a + u * b for p, s, u in zip(pts, sides, ups) for a, b in profile]
    faces = []
    for i in range(len(pts) - 1):
        for j in range(n):
            faces.append((i * n + j, i * n + (j + 1) % n, (i + 1) * n + (j + 1) % n, (i + 1) * n + j))
    if cap:
        faces.append(tuple(range(n)))
        faces.append(tuple(range((len(pts) - 1) * n, len(pts) * n)))
    return link(name, mesh(name, verts, faces), material, parent)


def arc_frames(a0, a1, steps):
    """Frames for sweeping a radial (r, z) profile around the pilot."""
    pts, sides, ups = [], [], []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append(Vector((0, 0, 0)))
        sides.append(Vector((math.sin(a), math.cos(a), 0)))
        ups.append(Vector((0, 0, 1)))
    return pts, sides, ups


def box(name, size, loc, material, parent=None, rot=(0, 0, 0), bev=0.003):
    sx, sy, sz = (s / 2 for s in size)
    verts = [(x, y, z) for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    o = link(name, mesh(name, verts, faces), material, parent, loc, rot)
    if bev:
        bevel(o, bev)
    return o


def plane(name, w, h, loc, material, parent=None, uv=False):
    """Flat quad in the local XZ plane, facing -Y (toward the pilot)."""
    me = mesh(name, [(-w / 2, 0, -h / 2), (w / 2, 0, -h / 2), (w / 2, 0, h / 2), (-w / 2, 0, h / 2)], [(0, 1, 2, 3)])
    if uv:
        layer = me.uv_layers.new()
        for li, co in zip(range(4), [(0, 0), (1, 0), (1, 1), (0, 1)]):
            layer.data[li].uv = co
    me.flip_normals()
    return link(name, me, material, parent, loc)


def torus(name, R, r, segs, minor, material, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), phase=0.0):
    verts, faces = [], []
    for i in range(segs):
        u = 2 * math.pi * i / segs + phase
        for j in range(minor):
            v = 2 * math.pi * j / minor
            verts.append(((R + r * math.cos(v)) * math.cos(u), (R + r * math.cos(v)) * math.sin(u), r * math.sin(v)))
    for i in range(segs):
        for j in range(minor):
            a = i * minor + j
            faces.append((a, i * minor + (j + 1) % minor, ((i + 1) % segs) * minor + (j + 1) % minor, ((i + 1) % segs) * minor + j))
    o = link(name, mesh(name, verts, faces), material, parent, loc, rot)
    o.data.shade_smooth()
    return o


def sphere(name, radius, material, parent=None, loc=(0, 0, 0), segs=24, rings=12, hemi=False):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    if hemi:
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -1e-4], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    o = link(name, me, material, parent, loc)
    me.shade_smooth()
    return o


def cylinder(name, radius, depth, material, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), segs=32):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=radius, radius2=radius, depth=depth)
    bm.to_mesh(me)
    bm.free()
    o = link(name, me, material, parent, loc, rot)
    return smooth_sharp(o)


def wire(o, thickness=0.0012):
    m = o.modifiers.new("Wire", "WIREFRAME")
    m.thickness = thickness
    m.use_replace = True
    return o


def anchor(name, ang, r, z, tilt=0.0):
    """Empty placed around the pilot, facing them. Children use local XZ as the
    'face' plane with -Y pointing at the pilot; tilt leans the top away."""
    e = bpy.data.objects.new(name, None)
    COL.objects.link(e)
    a = math.radians(ang)
    e.location = (r * math.sin(a), r * math.cos(a), z)
    e.rotation_euler = (-math.radians(tilt), 0, -a)
    e.empty_display_size = 0.05
    return e


FONT = None
for f in ("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
          "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"):
    if os.path.exists(f):
        FONT = bpy.data.fonts.load(f)
        FONT.pack()
        break


def text(name, body, size, loc, material, parent, align="CENTER"):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    if FONT:
        cu.font = FONT
    return link(name, cu, material, parent, loc, (math.pi / 2, 0, 0))


# ---------------------------------------------------------------- dash body
# Radial profile (r, z): knee wall, rounded lip, sloped top deck, front edge.
DASH = [(0.58, 0.45), (0.58, 0.84), (0.60, 0.885), (0.63, 0.90), (1.08, 0.98), (1.16, 0.93), (1.16, 0.45)]
bevel(sweep("Dash Body", *arc_frames(-80, 80, 96), DASH, M_HULL), 0.006, 3, 30)

SILL = [(1.16, 0.93), (2.0, 0.84), (2.0, 0.78), (1.16, 0.78)]
smooth_sharp(sweep("Nose Sill", *arc_frames(-80, 80, 96), SILL, M_DARK))

TUB = [(1.16, 0.0), (1.16, 1.0), (1.26, 1.04), (1.3, 1.0), (1.3, 0.0)]
smooth_sharp(sweep("Cockpit Tub", *arc_frames(80, 280, 96), TUB, M_HULL))
cylinder("Cockpit Floor", 1.2, 0.04, M_DARK, loc=(0, 0, 0.43), segs=96)

# Copper trim cap over the lip, plus light strips.
LIP = [(0.585, 0.86), (0.60, 0.89), (0.635, 0.906), (0.66, 0.909), (0.66, 0.902), (0.63, 0.896), (0.598, 0.882), (0.585, 0.86)]
smooth_sharp(sweep("Lip Trim", *arc_frames(-78, 78, 96), LIP[:-1], M_TRIM), 50)
sweep("Lip Light", *arc_frames(-76, 76, 96), [(0.67, 0.9045), (0.676, 0.9056), (0.676, 0.9086), (0.67, 0.9075)], G_STRIP)
sweep("Deck Light", *arc_frames(-70, 70, 96), [(1.045, 0.973), (1.06, 0.976), (1.06, 0.981), (1.045, 0.978)], G_STRIP_CYAN)
sweep("Sill Light", *arc_frames(-60, 60, 96), [(1.62, 0.875), (1.64, 0.873), (1.64, 0.879), (1.62, 0.881)], G_AMBER_SOFT)

# Raised armour plates on the sill.
for i, ang in enumerate((-46, -30, 30, 46)):
    e = anchor(f"Sill Plate Anchor {i}", ang, 1.42, 0.895, tilt=84)
    box(f"Sill Plate {i}", (0.2, 0.012, 0.22), (0, -0.006, 0), M_HULL, e, bev=0.004)
    for k in range(4):
        box(f"Sill Vent {i}.{k}", (0.14, 0.006, 0.012), (0, -0.014, -0.06 + k * 0.03), M_DARK, e, bev=0)


# ---------------------------------------------------------------- canopy frame
C = Vector((0, 1.35, 0.86))
U = Vector((0, 0.3, 1)).normalized()
X = Vector((1, 0, 0))
N = X.cross(U).normalized()
RX, RZ, SEG = 1.05, 0.98, 12
pts, sides, ups = [], [], []
for i in range(SEG + 1):
    t = math.pi * i / SEG
    pts.append(C + X * (-RX * math.cos(t)) + U * (RZ * math.sin(t)))
    sides.append(N)
    ups.append((X * (-math.cos(t) / RX) + U * (math.sin(t) / RZ)).normalized())
ARCH = [(-0.06, 0.0), (0.06, 0.0), (0.075, 0.035), (0.06, 0.075), (-0.06, 0.075), (-0.075, 0.035)]
bevel(sweep("Canopy Arch", pts, sides, ups, ARCH, M_HULL), 0.006, 2, 25)
sweep("Arch Light Amber", pts, sides, ups, [(-0.032, -0.004), (-0.024, -0.004), (-0.024, 0.0), (-0.032, 0.0)], G_STRIP)
sweep("Arch Light Red", pts, sides, ups, [(0.026, -0.003), (0.03, -0.003), (0.03, 0.0), (0.026, 0.0)], G_STRIP_RED)
# Clamp blocks at each facet joint.
for i in range(1, SEG):
    p, up = pts[i], ups[i]
    e = bpy.data.objects.new(f"Arch Clamp Anchor {i}", None)
    COL.objects.link(e)
    e.location = p + up * 0.04
    e.rotation_euler = up.to_track_quat("Z", "Y").to_euler()
    box(f"Arch Clamp {i}", (0.15, 0.06, 0.1), (0, 0, 0), M_TRIM if i % 3 == 0 else M_DARK, e, bev=0.008)

# Side rails running from the arch feet back past the pilot.
for sgn, nm in ((-1, "L"), (1, "R")):
    a, b = Vector((sgn * 1.05, 1.35, 0.86)), Vector((sgn * 1.32, -0.35, 1.0))
    rp = [a.lerp(b, k / 8) for k in range(9)]
    d = (b - a).normalized()
    side = d.cross(Vector((0, 0, 1))).normalized() * sgn
    rs, ru = [side] * 9, [Vector((0, 0, 1))] * 9
    bevel(sweep(f"Side Rail {nm}", rp, rs, ru, [(-0.07, 0), (0.07, 0), (0.07, 0.1), (0.04, 0.13), (-0.07, 0.13)], M_HULL), 0.006)
    sweep(f"Rail Light {nm}", rp, rs, ru, [(-0.072, 0.07), (-0.068, 0.07), (-0.068, 0.11), (-0.072, 0.11)], G_AMBER_SOFT)


# ---------------------------------------------------------------- displays
SCREENS = [
    # angle, colour, width, height
    (-50, AMBER, 0.32, 0.19),
    (-24, RED, 0.29, 0.18),
    (24, CYAN, 0.29, 0.18),
    (50, AMBER, 0.32, 0.19),
]
GLOW = {AMBER: G_AMBER, RED: G_RED, CYAN: G_CYAN}


def bar(name, parent, x, z, w, h, fill, material):
    plane(name + " Track", w, h, (x, -0.0045, z), M_DARK, parent)
    plane(name + " Fill", w * fill, h * 0.7, (x - w * (1 - fill) / 2, -0.0055, z), material, parent)


def screen(i, ang, color, w, h):
    e = anchor(f"Screen {i}", ang, 0.88, 0.95, tilt=28)
    g = GLOW[color]
    zc = h / 2 + 0.03
    box(f"Screen {i} Housing", (w + 0.035, 0.04, h + 0.035), (0, 0.02, zc), M_HULL, e, bev=0.008)
    box(f"Screen {i} Bezel", (w + 0.012, 0.004, h + 0.012), (0, -0.001, zc), M_DARK, e, bev=0.001)
    box(f"Screen {i} Stand", (w * 0.5, 0.03, 0.05), (0, 0.025, 0.012), M_TRIM, e, bev=0.004)
    plane(f"Screen {i} Glass", w, h, (0, -0.0035, zc), mat_screen(f"Screen Glass {i}", color), e, uv=True)
    # Tick strip along the top edge.
    for k in range(14):
        plane(f"Screen {i} Tick {k}", 0.003, 0.008, (-w / 2 + 0.02 + k * 0.006, -0.004, zc + h / 2 - 0.015), g, e)
    plane(f"Screen {i} Rule", w - 0.03, 0.0015, (0, -0.004, zc + h / 2 - 0.028), g, e)
    return e, g, zc


e, g, zc = screen(0, *SCREENS[0])
text("S0 Title", "REACTOR GRID", 0.016, (0.075, -0.005, zc + 0.048), g, e)
text("S0 Main", "CORE  STABLE", 0.03, (0, -0.005, zc + 0.008), g, e)
for k, (lbl, f) in enumerate((("A", 0.82), ("B", 0.64), ("C", 0.91))):
    text(f"S0 L{k}", lbl, 0.014, (-0.135, -0.005, zc - 0.035 - k * 0.02), g, e)
    bar(f"S0 Bar {k}", e, 0.01, zc - 0.035 - k * 0.02, 0.24, 0.01, f, g)

e, g, zc = screen(1, *SCREENS[1])
text("S1 Title", "VELOCITY", 0.016, (0.09, -0.005, zc + 0.044), g, e)
text("S1 Main", "212 m/s", 0.046, (0.025, -0.005, zc + 0.0), g, e)
box("S1 Icon", (0.035, 0.002, 0.035), (-0.095, -0.004, zc + 0.0), M_DARK, e, bev=0)
torus("S1 Icon Ring", 0.016, 0.0015, 32, 6, g, e, (-0.095, -0.006, zc + 0.0), (math.pi / 2, 0, 0))
bar("S1 Thrust", e, 0, zc - 0.055, 0.25, 0.012, 0.58, g)

e, g, zc = screen(2, *SCREENS[2])
text("S2 Title", "CONTACT  KESTREL-9", 0.016, (0, -0.005, zc + 0.044), g, e)
for k, R in enumerate((0.02, 0.035, 0.05)):
    torus(f"S2 Scope {k}", R, 0.0008, 48, 4, g, e, (-0.07, -0.005, zc - 0.008), (math.pi / 2, 0, 0))
torus("S2 Blip", 0.006, 0.002, 3, 4, G_RED, e, (-0.055, -0.006, zc + 0.01), (math.pi / 2, 0, 0))
text("S2 Hull", "HULL 64%", 0.022, (0.065, -0.005, zc + 0.015), g, e)
text("S2 Shd", "SHIELD 30%", 0.022, (0.065, -0.005, zc - 0.022), G_RED, e)
bar("S2 Range", e, 0.065, zc - 0.055, 0.12, 0.008, 0.4, g)

e, g, zc = screen(3, *SCREENS[3])
text("S3 Title", "ION LANCE", 0.03, (-0.03, -0.005, zc + 0.03), g, e)
text("S3 Sub", "CHARGE", 0.014, (-0.115, -0.005, zc - 0.005), g, e)
for k in range(10):
    plane(f"S3 Cell {k}", 0.017, 0.022, (-0.075 + k * 0.021, -0.005, zc - 0.005), g if k < 8 else M_DARK, e)
box("S3 Tag", (0.06, 0.002, 0.022), (0.11, -0.003, zc - 0.06), M_HULL, e, bev=0)
text("S3 Armed", "ARMED", 0.016, (0.11, -0.005, zc - 0.06), G_GREEN, e)


# ---------------------------------------------------------------- central holo radar
e = anchor("Radar", 0, 0.86, 0.94)
bevel(box("Radar Housing", (0.36, 0.3, 0.07), (0, 0, 0.035), M_HULL, e, bev=0), 0.01, 3)
cylinder("Radar Well", 0.14, 0.012, M_DARK, e, (0, 0, 0.068))
torus("Radar Collar", 0.145, 0.008, 64, 12, M_TRIM, e, (0, 0, 0.074))
for k, R in enumerate((0.03, 0.06, 0.09, 0.12)):
    torus(f"Radar Ring {k}", R, 0.0012, 64, 4, H_AMBER, e, (0, 0, 0.078))
wire(sphere("Radar Dome", 0.125, H_AMBER, e, (0, 0, 0.078), segs=20, rings=10, hemi=True), 0.0012)
torus("Radar Sweep", 0.1, 0.0015, 48, 4, H_AMBER, e, (0, 0, 0.078), (math.radians(70), 0, math.radians(30)))
for k, (p, m) in enumerate((((0.03, 0.04, 0.12), G_RED), ((-0.05, -0.02, 0.1), G_RED), ((0.06, -0.05, 0.09), G_CYAN), ((0, 0, 0.08), G_WHITE))):
    sphere(f"Radar Blip {k}", 0.007, m, e, p, segs=8, rings=4)
plane("Radar Halo", 0.55, 0.4, (0, 0.06, 0.13), HALO_AMBER, e, uv=True)
for sgn in (-1, 1):
    box(f"Radar Fin {sgn}", (0.025, 0.12, 0.12), (sgn * 0.19, 0.03, 0.08), M_HULL, e, rot=(0, sgn * math.radians(-12), 0), bev=0.005)
    sphere(f"Radar Beacon {sgn}", 0.009, G_RED, e, (sgn * 0.2, 0.06, 0.15), segs=12, rings=6)


# ---------------------------------------------------------------- floating holograms
e = anchor("Holo Planet", -37, 1.02, 1.21)
wire(sphere("Holo Planet Globe", 0.055, H_AMBER, e, segs=18, rings=10), 0.0011)
torus("Holo Planet Ring", 0.09, 0.0012, 64, 4, H_AMBER, e, rot=(math.radians(70), math.radians(18), 0))
sphere("Holo Moon", 0.009, G_AMBER, e, (0.085, 0, 0.05), segs=10, rings=6)
plane("Holo Planet Halo", 0.4, 0.4, (0, 0.03, 0), HALO_AMBER, e, uv=True)
text("Holo Planet Label", "NAV  OBERON-IV", 0.016, (0, 0, -0.09), H_AMBER, e)

e = anchor("Holo Reticle", 37, 1.02, 1.21)
torus("Reticle Outer", 0.07, 0.0016, 4, 4, H_CYAN, e, rot=(math.pi / 2, 0, 0))
torus("Reticle Inner", 0.045, 0.0012, 4, 4, H_CYAN, e, rot=(math.pi / 2, 0, 0), phase=math.pi / 4)
torus("Reticle Core", 0.016, 0.0018, 3, 4, G_RED, e, rot=(math.pi / 2, 0, 0), phase=-math.pi / 2)
plane("Holo Reticle Halo", 0.38, 0.38, (0, 0.03, 0), HALO_CYAN, e, uv=True)
text("Holo Reticle Label", "LOCK  2.4 km", 0.016, (0, 0, -0.095), H_CYAN, e)


# ---------------------------------------------------------------- switches & gauges
BUTTON_GLOWS = [G_AMBER, G_AMBER, G_GREEN, G_RED, G_CYAN, None, None]


def button_cluster(name, ang, r, cols, rows):
    z = 0.90 + 0.08 * (r - 0.63) / 0.45 + 0.002
    e = anchor(name, ang, r, z, tilt=80)
    pw, ph = cols * 0.022 + 0.014, rows * 0.022 + 0.014
    box(name + " Plate", (pw, 0.006, ph), (0, -0.003, 0), M_DARK, e, bev=0.002)
    for c in range(cols):
        for rr in range(rows):
            x, zz = -pw / 2 + 0.018 + c * 0.022, -ph / 2 + 0.018 + rr * 0.022
            gm = random.choice(BUTTON_GLOWS)
            box(f"{name} Btn {c}.{rr}", (0.016, 0.008, 0.012), (x, -0.009, zz), M_RUBBER, e, bev=0.002)
            if gm:
                plane(f"{name} Lamp {c}.{rr}", 0.01, 0.004, (x, -0.0135, zz + 0.002), gm, e)


def toggle_row(name, ang, r, n):
    z = 0.90 + 0.08 * (r - 0.63) / 0.45 + 0.002
    e = anchor(name, ang, r, z, tilt=80)
    box(name + " Plate", (n * 0.024 + 0.02, 0.006, 0.04), (0, -0.003, 0), M_HULL, e, bev=0.002)
    for k in range(n):
        x = -n * 0.012 + 0.012 + k * 0.024
        cylinder(f"{name} Base {k}", 0.006, 0.006, M_TRIM, e, (x, -0.008, 0), (math.pi / 2, 0, 0), segs=12)
        lean = math.radians(25 if k % 3 else -25)
        cylinder(f"{name} Lever {k}", 0.0022, 0.03, M_TRIM, e, (x, -0.02, 0.006 if lean > 0 else -0.006), (math.pi / 2 + lean, 0, 0), segs=8)
        plane(f"{name} Lamp {k}", 0.008, 0.003, (x, -0.0065, -0.015), G_GREEN if k % 3 else G_RED, e)


button_cluster("Keys L1", -38, 0.74, 4, 2)
button_cluster("Keys R1", 38, 0.74, 4, 2)
button_cluster("Keys L2", -62, 0.76, 3, 3)
button_cluster("Keys R2", 62, 0.76, 3, 3)
toggle_row("Toggles L", -14, 0.72, 4)
toggle_row("Toggles R", 14, 0.72, 4)

for sgn in (-1, 1):
    e = anchor(f"Gauge Pod {sgn}", sgn * 70, 0.92, 0.97, tilt=20)
    box(f"Gauge Pod Body {sgn}", (0.2, 0.05, 0.1), (0, 0.02, 0.05), M_HULL, e, bev=0.008)
    for k, x in enumerate((-0.05, 0.05)):
        cylinder(f"Gauge {sgn}.{k} Face", 0.036, 0.006, M_DARK, e, (x, -0.006, 0.05), (math.pi / 2, 0, 0))
        torus(f"Gauge {sgn}.{k} Bezel", 0.037, 0.004, 32, 8, M_TRIM, e, (x, -0.009, 0.05), (math.pi / 2, 0, 0))
        torus(f"Gauge {sgn}.{k} Scale", 0.026, 0.0012, 32, 4, G_AMBER if k else G_CYAN, e, (x, -0.0105, 0.05), (math.pi / 2, 0, 0))
        box(f"Gauge {sgn}.{k} Needle", (0.026, 0.002, 0.0025), (x + 0.008, -0.011, 0.056), G_RED, e,
            rot=(0, math.radians(-30 + 50 * k), 0), bev=0)


# ---------------------------------------------------------------- world, lights, cameras
world = bpy.data.worlds.new("Deep Space")
scene.world = world
nodes, links = _nodes(world)
nodes.clear()
tc = nodes.new("ShaderNodeTexCoord")
out = nodes.new("ShaderNodeOutputWorld")


def star_layer(scale, radius, keep, gain):
    v = nodes.new("ShaderNodeTexVoronoi")
    v.inputs["Scale"].default_value = scale
    links.new(tc.outputs["Generated"], v.inputs["Vector"])
    core = nodes.new("ShaderNodeMapRange")
    core.inputs["From Min"].default_value = radius
    core.inputs["From Max"].default_value = 0.0
    links.new(v.outputs["Distance"], core.inputs["Value"])
    sep = nodes.new("ShaderNodeSeparateColor")
    links.new(v.outputs["Color"], sep.inputs[0])
    gate = nodes.new("ShaderNodeMapRange")
    gate.inputs["From Min"].default_value = keep
    gate.inputs["From Max"].default_value = 1.0
    gate.inputs["To Max"].default_value = gain
    links.new(sep.outputs[0], gate.inputs["Value"])
    mul = nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    links.new(core.outputs[0], mul.inputs[0])
    links.new(gate.outputs[0], mul.inputs[1])
    return mul


small = star_layer(260, 0.16, 0.86, 6)
big = star_layer(70, 0.07, 0.93, 25)
stars = nodes.new("ShaderNodeMath")
stars.operation = "ADD"
links.new(small.outputs[0], stars.inputs[0])
links.new(big.outputs[0], stars.inputs[1])
bg_stars = nodes.new("ShaderNodeBackground")
bg_stars.inputs["Color"].default_value = (0.85, 0.9, 1.0, 1)
links.new(stars.outputs[0], bg_stars.inputs["Strength"])

noise = nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 1.6
noise.inputs["Detail"].default_value = 10
links.new(tc.outputs["Generated"], noise.inputs["Vector"])
ramp = nodes.new("ShaderNodeValToRGB")
cr = ramp.color_ramp
cr.elements[0].position, cr.elements[0].color = 0.42, (0.002, 0.003, 0.008, 1)
cr.elements[1].position, cr.elements[1].color = 0.62, (0.02, 0.035, 0.11, 1)
el = cr.elements.new(0.75)
el.color = (0.07, 0.02, 0.1, 1)
links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
bg_neb = nodes.new("ShaderNodeBackground")
links.new(ramp.outputs["Color"], bg_neb.inputs["Color"])
add = nodes.new("ShaderNodeAddShader")
links.new(bg_stars.outputs[0], add.inputs[0])
links.new(bg_neb.outputs[0], add.inputs[1])
links.new(add.outputs[0], out.inputs[0])


def light(name, kind, loc, rot, energy, color, size=0.2):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.size = size
    o = bpy.data.objects.new(name, ld)
    COL.objects.link(o)
    o.location = loc
    o.rotation_euler = rot
    return o


light("Radar Glow", "POINT", (0, 0.82, 1.12), (0, 0, 0), 6, AMBER)
for i, (ang, color, _, _) in enumerate(SCREENS):
    a = math.radians(ang)
    light(f"Screen Spill {i}", "POINT", (0.78 * math.sin(a), 0.78 * math.cos(a), 1.03), (0, 0, 0), 2.5, color)
light("Starlight", "SUN", (0, 0, 3), (math.radians(-35), 0, math.radians(180)), 0.25, (0.55, 0.65, 1.0))
light("Cabin Fill", "AREA", (0, -0.3, 1.6), (0, 0, 0), 6, (1.0, 0.35, 0.15), size=1.2)
light("Arch Wash", "AREA", (0, 1.0, 0.95), (math.radians(-60), 0, 0), 25, (1.0, 0.3, 0.08), size=1.5)


def camera(name, loc, target, lens):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_start = 0.02
    o = bpy.data.objects.new(name, cd)
    COL.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return o


CAM_PILOT = camera("Pilot View", (0, -0.3, 1.25), (0, 2.0, 1.15), 15)
CAM_ORBIT = camera("Overview", (1.6, -1.1, 2.0), (0, 0.9, 0.95), 24)
scene.camera = CAM_PILOT

# ---------------------------------------------------------------- render settings & bloom
r = scene.render
r.engine = "BLENDER_EEVEE"
r.resolution_x, r.resolution_y = 2000, 844
scene.eevee.taa_render_samples = 64
scene.eevee.use_raytracing = True
scene.view_settings.view_transform = "AgX"
try:
    scene.view_settings.look = "AgX - Punchy"
except TypeError:
    pass

comp = bpy.data.node_groups.new("Bloom", "CompositorNodeTree")
comp.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
rl = comp.nodes.new("CompositorNodeRLayers")
gl = comp.nodes.new("CompositorNodeGlare")
gl.inputs["Type"].default_value = "Bloom"
gl.inputs["Quality"].default_value = "High"
gl.inputs["Threshold"].default_value = 0.6
gl.inputs["Strength"].default_value = 0.7
gl.inputs["Size"].default_value = 0.7
go = comp.nodes.new("NodeGroupOutput")
comp.links.new(rl.outputs["Image"], gl.inputs["Image"])
comp.links.new(gl.outputs["Image"], go.inputs[0])
scene.compositing_node_group = comp

print("OBJECTS", len(bpy.data.objects))

# ---------------------------------------------------------------- outputs
if "--render" in ARGS:
    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
    for cam, fname in ((CAM_PILOT, "pilot_view.png"), (CAM_ORBIT, "overview.png")):
        scene.camera = cam
        r.filepath = os.path.join(OUT, "renders", fname)
        bpy.ops.render.render(write_still=True)
    scene.camera = CAM_PILOT

if "--save" in ARGS:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "cockpit_dash.blend"))
    # glTF has no text objects: bake them to meshes for the export only.
    for o in bpy.data.objects:
        o.select_set(o.type == "FONT")
    bpy.context.view_layer.objects.active = next((o for o in bpy.data.objects if o.type == "FONT"), None)
    bpy.ops.object.convert(target="MESH")
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "cockpit_dash.glb"), export_apply=True,
                              export_cameras=True, export_lights=True)

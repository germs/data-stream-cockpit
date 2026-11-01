"""KESTREL-9: a flying mechanical cobra, built procedurally for Blender 5.x.

Black armoured segments, acid-lime belly scutes, glowing green flank tubes, a spiked spine and a flaring hood.
The body is Geometry Nodes on a straight 70 m spine: a travelling wave (driven by scene time, so no Python at
render) swims it through the air, fading out toward the head so the head flies steady.

Local space: tail at the origin, head at +Y (the direction it flies), Z up. Units are metres.

  KESTREL | Body         GN body; inputs Wave Amp / Wave Speed on the modifier
   KESTREL | Head        empty at the neck; custom props hood (0 folded..1 flared), jaw (0..1), tongue (0..1)

Run:
  Blender --background --factory-startup --python creature_kestrel.py -- --lookdev [--render] [--save]
  (or import build() from another script to drop the creature into an open scene)
"""
import bpy, bmesh, math, os, sys
from mathutils import Vector, Matrix

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

LENGTH = 70.0       # spine length
RADIUS = 2.1        # body radius at its thickest
HEAD_SCALE = 1.4    # the head is modelled for a 1.5 m neck; scale it to the body
SEGMENTS = 70       # one armour ring per metre
D = math.radians


# ---------------------------------------------------------------- materials
def mat_plastic(name, color, rough=0.3, metal=0.0, emit=0.0):
    m = bpy.data.materials.new(name)
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*color, 1)
        b.inputs["Emission Strength"].default_value = emit
    return m


def mat_glow(name, color, strength):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color, 1)
    e.inputs["Strength"].default_value = strength
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs[0])
    return m


def materials():
    return {
        "armor": mat_plastic("KESTREL Armor Black", (0.012, 0.012, 0.014), rough=0.22),
        "dark": mat_plastic("KESTREL Armor Graphite", (0.05, 0.052, 0.058), rough=0.35, metal=0.4),
        "metal": mat_plastic("KESTREL Spike Steel", (0.25, 0.26, 0.28), rough=0.25, metal=1.0),
        "lime": mat_plastic("KESTREL Lime Plate", (0.55, 0.85, 0.02), rough=0.3, emit=0.35),
        "glow": mat_glow("KESTREL Green Glow", (0.15, 1.0, 0.12), 7),
        "eye": mat_glow("KESTREL Eye Glow", (0.3, 1.0, 0.15), 40),
        "fang": mat_plastic("KESTREL Fang", (0.85, 0.83, 0.78), rough=0.35),
        "tongue": mat_plastic("KESTREL Tongue Red", (0.8, 0.05, 0.02), rough=0.4, emit=0.6),
        "mouth": mat_plastic("KESTREL Mouth", (0.15, 0.01, 0.01), rough=0.6),
    }


# ---------------------------------------------------------------- mesh helpers
def obj(name, me, mat, coll, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), bevel=0.0):
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    if mat:
        me.materials.append(mat)
    o.parent = parent
    o.location, o.rotation_euler = loc, rot
    if bevel:
        m = o.modifiers.new("Bevel", "BEVEL")
        m.width, m.segments, m.limit_method = bevel, 2, "ANGLE"
        m.harden_normals = True
        me.shade_smooth()
    return o


def box(name, size, mat, coll, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), front=(1, 1), bevel=0.04):
    """Box; front=(sx, sz) scales the +Y face, for wedges and tapered plates."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
        if v.co.y > 0:
            v.co.x *= front[0]
            v.co.z *= front[1]
    bm.to_mesh(me)
    bm.free()
    return obj(name, me, mat, coll, parent, loc, rot, bevel)


def cone(name, r1, r2, depth, mat, coll, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), segs=8, caps=True, bevel=0.0):
    """Cone along local +Z from base (z=0) to tip (z=depth)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, segments=segs, radius1=r1, radius2=r2, depth=depth,
                          matrix=Matrix.Translation((0, 0, depth / 2)))
    bm.to_mesh(me)
    bm.free()
    return obj(name, me, mat, coll, parent, loc, rot, bevel)


def empty(name, coll, parent=None, loc=(0, 0, 0), rot=(0, 0, 0), size=0.5):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = size
    coll.objects.link(e)
    e.parent, e.location, e.rotation_euler = parent, loc, rot
    return e


def drive(owner, path, index, expr, src, prop):
    d = owner.driver_add(path, index).driver
    d.type = "SCRIPTED"
    v = d.variables.new()
    v.name = "p"
    v.targets[0].id = src
    v.targets[0].data_path = f'["{prop}"]'
    d.expression = expr


# ---------------------------------------------------------------- instanced parts (unit radius, ring along Y)
def build_parts(M, root_coll):
    seg = bpy.data.collections.new("KESTREL | Segment")
    spike = bpy.data.collections.new("KESTREL | Spike")
    tail = bpy.data.collections.new("KESTREL | Tail")
    for c in (seg, spike, tail):
        root_coll.children.link(c)
    # armour ring: octagonal shell, flared at the front so rings stack like scales
    ring = cone("Seg Ring", 1.0, 0.86, 1.08, M["armor"], seg, rot=(D(-90), 0, D(22.5)), segs=8, caps=False, bevel=0.03)
    ring.location = (0, 0.54, 0)
    sol = ring.modifiers.new("Thick", "SOLIDIFY")
    sol.thickness = 0.08
    ring.modifiers.move(1, 0)
    box("Seg Belly Scute", (1.25, 0.95, 0.22), M["lime"], seg, loc=(0, 0.05, -0.9), front=(0.75, 1.0), bevel=0.05)
    for sx in (-1, 1):
        box(f"Seg Flank {sx}", (0.18, 0.7, 0.5), M["dark"], seg, loc=(sx * 0.98, 0.0, 0.1), rot=(0, sx * D(-12), 0), bevel=0.03)
        box(f"Seg Clamp {sx}", (0.22, 0.25, 0.3), M["armor"], seg, loc=(sx * 0.95, 0.3, -0.38), bevel=0.03)
    box("Seg Dorsal Plate", (0.7, 0.9, 0.16), M["dark"], seg, loc=(0, 0.0, 0.98), front=(0.8, 1), bevel=0.03)
    # dorsal spike, raked back
    cone("Spike", 0.22, 0.0, 1.3, M["armor"], spike, loc=(0, 0.1, 0.95), rot=(D(-38), 0, 0), segs=6, bevel=0.0)
    cone("Spike Tip", 0.07, 0.0, 0.5, M["metal"], spike, loc=(0, -0.55, 1.95), rot=(D(-50), 0, 0), segs=6)
    # tail blade: a fan of steel spikes pointing back
    for k, (ax, az) in enumerate(((0, 0), (25, 15), (-25, 15), (0, 35), (12, -20), (-12, -20))):
        cone(f"Tail Spike {k}", 0.18, 0.0, 2.2 - 0.25 * k, M["metal" if k % 2 else "armor"], tail,
             rot=(D(90 + az), 0, D(180 + ax)), segs=6)
    return seg, spike, tail


# ---------------------------------------------------------------- body geometry nodes
def build_body_nodes(seg, spike, tail, glow_mat):
    g = bpy.data.node_groups.new("KESTREL Body", "GeometryNodeTree")
    g.is_modifier = True
    ins = {}
    for nm, typ, dv in (("Wave Amp", "NodeSocketFloat", 3.5), ("Wave Length", "NodeSocketFloat", 26.0),
                        ("Wave Speed", "NodeSocketFloat", 0.55), ("Lift Amp", "NodeSocketFloat", 1.2)):
        s = g.interface.new_socket(nm, in_out="INPUT", socket_type=typ)
        s.default_value = dv
        ins[nm] = s.identifier
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = g.nodes, g.links
    x = [0]

    def node(t, **props):
        n = N.new(t)
        for k, v in props.items():
            setattr(n, k, v)
        n.location = (x[0], 0)
        x[0] += 160
        return n

    def math(op, a, b=None, c=None):
        n = node("ShaderNodeMath", operation=op)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L.new(v, n.inputs[i])
        return n.outputs[0]

    def sock(n, name, typ):
        return next(s for s in n.inputs if s.name == name and s.type == typ)

    gi = node("NodeGroupInput")
    line = node("GeometryNodeCurvePrimitiveLine")
    line.inputs["Start"].default_value = (0, 0, 0)
    line.inputs["End"].default_value = (0, LENGTH, 0)
    res = node("GeometryNodeResampleCurve")
    L.new(line.outputs[0], res.inputs["Curve"])
    res.inputs["Count"].default_value = SEGMENTS + 1
    u = node("GeometryNodeSplineParameter").outputs["Factor"]
    t = node("GeometryNodeInputSceneTime").outputs["Seconds"]

    # envelope: full wave along the tail and body, fading to nothing over the neck
    env_n = node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
    L.new(u, env_n.inputs["Value"])
    env_n.inputs["From Min"].default_value, env_n.inputs["From Max"].default_value = 0.55, 0.97
    env_n.inputs["To Min"].default_value, env_n.inputs["To Max"].default_value = 1.0, 0.0
    env = env_n.outputs[0]
    # phase = 2*pi*(s/len + speed*t): the wave runs head -> tail, the way a swimming snake pushes
    s_over = math("DIVIDE", math("MULTIPLY", u, LENGTH), gi.outputs["Wave Length"])
    phase = math("MULTIPLY", math("ADD", s_over, math("MULTIPLY", t, gi.outputs["Wave Speed"])), 2 * math_pi())
    xoff = math("MULTIPLY", math("MULTIPLY", math("SINE", phase), gi.outputs["Wave Amp"]), env)
    zoff = math("MULTIPLY", math("MULTIPLY", math("SINE", math("ADD", math("MULTIPLY", phase, 0.5), 1.3)),
                                 gi.outputs["Lift Amp"]), env)
    off = node("ShaderNodeCombineXYZ")
    L.new(xoff, off.inputs["X"])
    L.new(zoff, off.inputs["Z"])
    setp = node("GeometryNodeSetPosition")
    L.new(res.outputs[0], setp.inputs["Geometry"])
    L.new(off.outputs[0], setp.inputs["Offset"])

    # radius: tapered tail, full body, slight neck pinch under the hood
    tap = node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
    L.new(u, tap.inputs["Value"])
    tap.inputs["From Min"].default_value, tap.inputs["From Max"].default_value = 0.0, 0.45
    tap.inputs["To Min"].default_value, tap.inputs["To Max"].default_value = 0.22, 1.0
    neck = node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
    L.new(u, neck.inputs["Value"])
    neck.inputs["From Min"].default_value, neck.inputs["From Max"].default_value = 0.88, 1.0
    neck.inputs["To Min"].default_value, neck.inputs["To Max"].default_value = 1.0, 0.85
    r = math("MULTIPLY", math("MULTIPLY", tap.outputs[0], neck.outputs[0]), RADIUS)
    store = node("GeometryNodeStoreNamedAttribute", data_type="FLOAT", domain="POINT")
    L.new(setp.outputs[0], store.inputs["Geometry"])
    store.inputs["Name"].default_value = "r"
    L.new(r, sock(store, "Value", "VALUE"))
    store_u = node("GeometryNodeStoreNamedAttribute", data_type="FLOAT", domain="POINT")
    L.new(store.outputs[0], store_u.inputs["Geometry"])
    store_u.inputs["Name"].default_value = "u"
    L.new(u, sock(store_u, "Value", "VALUE"))
    curve = store_u.outputs[0]

    def attr(name):
        n = node("GeometryNodeInputNamedAttribute", data_type="FLOAT")
        n.inputs["Name"].default_value = name
        return next(s for s in n.outputs if s.type == "VALUE" and s.enabled)

    # points with a frame: Y along the spine, Z kept up
    c2p = node("GeometryNodeCurveToPoints", mode="EVALUATED")
    L.new(curve, c2p.inputs["Curve"])
    al1 = node("FunctionNodeAlignRotationToVector", axis="Y", pivot_axis="AUTO")
    L.new(c2p.outputs["Tangent"], al1.inputs["Vector"])
    al2 = node("FunctionNodeAlignRotationToVector", axis="Z", pivot_axis="Y")
    L.new(al1.outputs[0], al2.inputs["Rotation"])
    al2.inputs["Vector"].default_value = (0, 0, 1)
    rot = al2.outputs[0]
    idx = node("GeometryNodeInputIndex").outputs[0]

    def instances(coll, selection, scale):
        ci = node("GeometryNodeCollectionInfo", transform_space="ORIGINAL")
        ci.inputs["Collection"].default_value = coll
        iop = node("GeometryNodeInstanceOnPoints")
        L.new(c2p.outputs["Points"], iop.inputs["Points"])
        L.new(ci.outputs[0], iop.inputs["Instance"])
        L.new(rot, iop.inputs["Rotation"])
        L.new(scale, iop.inputs["Scale"])
        if selection is not None:
            L.new(selection, iop.inputs["Selection"])
        return iop.outputs[0]

    def cmp_lt(a, b):
        n = node("FunctionNodeCompare", data_type="FLOAT", operation="LESS_THAN")
        L.new(a, n.inputs["A"])
        if isinstance(b, (int, float)):
            n.inputs["B"].default_value = b
        else:
            L.new(b, n.inputs["B"])
        return n.outputs[0]

    rr = attr("r")
    uu = attr("u")
    seg_scale = node("ShaderNodeCombineXYZ")
    L.new(rr, seg_scale.inputs["X"])
    seg_scale.inputs["Y"].default_value = 1.0
    L.new(rr, seg_scale.inputs["Z"])
    # skip the last ring: the head's collar covers it
    body = instances(seg, cmp_lt(idx, SEGMENTS), seg_scale.outputs[0])
    every2 = cmp_lt(math("FLOORED_MODULO", idx, 2), 0.5)
    sp_sel = node("FunctionNodeBooleanMath", operation="AND")
    L.new(every2, sp_sel.inputs[0])
    L.new(cmp_lt(idx, SEGMENTS - 3), sp_sel.inputs[1])
    spikes = instances(spike, sp_sel.outputs[0], math("MULTIPLY", rr, math("ADD", 0.45, math("MULTIPLY", uu, 0.9))))
    tip = instances(tail, cmp_lt(idx, 0.5), math("MULTIPLY", rr, 2.2))

    # glowing tubes along both flanks
    tan = node("GeometryNodeInputTangent").outputs[0]
    side = node("ShaderNodeVectorMath", operation="CROSS_PRODUCT")
    L.new(tan, side.inputs[0])
    side.inputs[1].default_value = (0, 0, 1)
    side_n = node("ShaderNodeVectorMath", operation="NORMALIZE")
    L.new(side.outputs[0], side_n.inputs[0])
    tubes = []
    for sx in (-1.0, 1.0):
        sc = node("ShaderNodeVectorMath", operation="SCALE")
        L.new(side_n.outputs[0], sc.inputs[0])
        L.new(math("MULTIPLY", rr, sx * 1.12), sc.inputs["Scale"])
        down = node("ShaderNodeVectorMath", operation="ADD")
        L.new(sc.outputs[0], down.inputs[0])
        dz = node("ShaderNodeCombineXYZ")
        L.new(math("MULTIPLY", rr, -0.15), dz.inputs["Z"])
        L.new(dz.outputs[0], down.inputs[1])
        sp = node("GeometryNodeSetPosition")
        L.new(curve, sp.inputs["Geometry"])
        L.new(down.outputs[0], sp.inputs["Offset"])
        rad = node("GeometryNodeSetCurveRadius")
        L.new(sp.outputs[0], rad.inputs["Curve"])
        L.new(math("MULTIPLY", rr, 0.075), rad.inputs["Radius"])
        circ = node("GeometryNodeCurvePrimitiveCircle")
        circ.inputs["Resolution"].default_value = 8
        circ.inputs["Radius"].default_value = 1.0
        c2m = node("GeometryNodeCurveToMesh")
        L.new(rad.outputs[0], c2m.inputs["Curve"])
        L.new(circ.outputs[0], c2m.inputs["Profile Curve"])
        if "Scale" in c2m.inputs:
            radn = node("GeometryNodeInputRadius")
            L.new(radn.outputs[0], c2m.inputs["Scale"])
        tubes.append(c2m.outputs[0])
    tube_join = node("GeometryNodeJoinGeometry")
    for tb in tubes:
        L.new(tb, tube_join.inputs[0])
    setm = node("GeometryNodeSetMaterial")
    L.new(tube_join.outputs[0], setm.inputs["Geometry"])
    setm.inputs["Material"].default_value = glow_mat

    join = node("GeometryNodeJoinGeometry")
    for geo in (setm.outputs[0], tip, spikes, body):
        L.new(geo, join.inputs[0])
    go = node("NodeGroupOutput")
    L.new(join.outputs[0], go.inputs[0])
    return g, ins


def math_pi():
    return math.pi


# ---------------------------------------------------------------- head
# Faceted cross-section for lofted head parts: x, z in [-1, 1]; flat-ish belly, chamfered crown.
PROFILE = [(1.0, -0.6), (1.0, 0.25), (0.8, 0.8), (0.4, 1.0), (-0.4, 1.0), (-0.8, 0.8), (-1.0, 0.25), (-1.0, -0.6),
           (-0.6, -1.0), (0.6, -1.0)]


def loft(name, sections, mat, coll, parent=None, loc=(0, 0, 0), bevel=0.05, profile=PROFILE):
    """Hard-surface loft along +Y. sections: (y, half_width, top_z, bottom_z)."""
    verts, faces, n = [], [], len(profile)
    for y, hw, top, bot in sections:
        mid, hh = (top + bot) / 2, (top - bot) / 2
        verts += [(px * hw, y, mid + pz * hh) for px, pz in profile]
    for i in range(len(sections) - 1):
        for j in range(n):
            faces.append((i * n + j, i * n + (j + 1) % n, (i + 1) * n + (j + 1) % n, (i + 1) * n + j))
    faces.append(tuple(range(n)))
    faces.append(tuple(range((len(sections) - 1) * n, len(sections) * n)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return obj(name, me, mat, coll, parent, loc, bevel=bevel)


# One-piece hood. Points live in "hood space": th = angle round the head (0 = right, 90 = top), t = 0 at the
# neck .. 1 at the rim, l = sideways offset (m), d = offset toward the front (m). hood_point maps that to the
# head's space for any fold amount, so the basis (flared) and the "Folded" shape key share one topology.
HOOD_A, HOOD_B, HOOD_IN = 4.4, 3.5, 1.45
HOOD_TH = (-62.0, 242.0)


def hood_point(th, t, l, d, fold):
    a = math.radians(th)
    ell = HOOD_A * HOOD_B / math.sqrt((HOOD_B * math.cos(a)) ** 2 + (HOOD_A * math.sin(a)) ** 2)
    rho = HOOD_IN + (ell - HOOD_IN) * t
    tan = Vector((-math.sin(a), 0, math.cos(a)))
    p = Vector((rho * math.cos(a), -0.4 + 0.75 * t * t, 0.75 + rho * math.sin(a) * 0.92)) + tan * l + Vector((0, d, 0))
    # folded: the hood's sides collapse against the neck and sweep back along it
    q = p.copy()
    q.x = math.copysign(HOOD_IN * 0.9 + max(abs(p.x) - HOOD_IN, 0) * 0.18, p.x) if abs(p.x) > 1e-6 else 0.0
    q.z = 0.75 + (p.z - 0.75) * 0.3
    q.y = p.y - 2.6 * t - 0.3
    return p.lerp(q, fold)


def hood_part(name, params, faces, mat, coll, parent, head, smooth=False, solid=0.0, sink=0.0):
    """sink: how far the part slides back into the membrane when folded (hides the glow veins)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(hood_point(*p, 0.0)) for p in params], [], faces)
    o = obj(name, me, mat, coll, parent)
    if smooth:
        me.shade_smooth()
    if solid:
        so = o.modifiers.new("Thick", "SOLIDIFY")
        so.thickness, so.offset = solid, 0
    o.shape_key_add(name="Flared")
    k = o.shape_key_add(name="Folded")
    for i, p in enumerate(params):
        th, t, l, dd = p
        k.data[i].co = hood_point(th, t, l, dd - sink, 1.0)
    d = k.driver_add("value").driver
    d.type = "SCRIPTED"
    v = d.variables.new()
    v.name = "p"
    v.targets[0].id = head
    v.targets[0].data_path = '["hood"]'
    d.expression = "1 - p"
    return o


def strip(th, t0, t1, w, d0, d1, steps=8):
    """Params + faces for a raised box-section strip along one hood radius."""
    params, faces = [], []
    ring = [(-w, d0), (w, d0), (w, d1), (-w, d1)]
    for i in range(steps + 1):
        t = t0 + (t1 - t0) * i / steps
        params += [(th, t, l, d) for l, d in ring]
    for i in range(steps):
        for j in range(4):
            faces.append((i * 4 + j, i * 4 + (j + 1) % 4, (i + 1) * 4 + (j + 1) % 4, (i + 1) * 4 + j))
    faces += [(0, 1, 2, 3), tuple(range(steps * 4, steps * 4 + 4))]
    return params, faces


def merge(parts):
    params, faces = [], []
    for p, f in parts:
        off = len(params)
        params += p
        faces += [tuple(i + off for i in face) for face in f]
    return params, faces


def build_hood(M, coll, head):
    th0, th1 = HOOD_TH
    NT, NR = 34, 6
    # membrane: rings from neck to rim
    params = [(th0 + (th1 - th0) * i / NT, j / NR, 0.0, 0.0) for i in range(NT + 1) for j in range(NR + 1)]
    faces = [(i * (NR + 1) + j, (i + 1) * (NR + 1) + j, (i + 1) * (NR + 1) + j + 1, i * (NR + 1) + j + 1)
             for i in range(NT) for j in range(NR)]
    hood_part("Hood Membrane", params, faces, M["armor"], coll, head, head, smooth=True, solid=0.14)
    # lime collar band round the head, on the front face
    p2 = [(th0 + (th1 - th0) * i / NT, 0.04 + 0.26 * j, 0.0, 0.1) for i in range(NT + 1) for j in range(2)]
    f2 = [(i * 2, (i + 1) * 2, (i + 1) * 2 + 1, i * 2 + 1) for i in range(NT)]
    hood_part("Hood Collar Band", p2, f2, M["lime"], coll, head, head, solid=0.08)
    ribs = [th0 + 8 + (th1 - th0 - 16) * k / 8 for k in range(9)]
    hood_part("Hood Ribs", *merge(strip(th, 0.08, 1.0, 0.16, 0.0, 0.28) for th in ribs), M["dark"], coll, head, head)
    hood_part("Hood Veins", *merge(strip(th, 0.35, 0.95, 0.05, 0.28, 0.33) for th in ribs), M["glow"], coll, head, head,
              sink=0.45)
    # rim spikes: square pyramids pushed out past the rim at each rib
    sp, sf = [], []
    for th in ribs:
        o = len(sp)
        sp += [(th, 0.97, l, d) for l, d in ((-0.22, -0.2), (0.22, -0.2), (0.22, 0.25), (-0.22, 0.25))] + [(th, 1.42, 0.0, 0.0)]
        sf += [(o, o + 1, o + 4), (o + 1, o + 2, o + 4), (o + 2, o + 3, o + 4), (o + 3, o, o + 4), (o + 3, o + 2, o + 1, o)]
    hood_part("Hood Spikes", sp, sf, M["metal"], coll, head, head)


def build_head(M, coll, body):
    head = empty("KESTREL | Head", coll, body, loc=(0, LENGTH, 0), size=2.0)
    head.scale = (HEAD_SCALE,) * 3
    head["hood"] = 0.0
    head["jaw"] = 0.0
    head["tongue"] = 0.0
    for p, desc in (("hood", "0 folded .. 1 flared"), ("jaw", "0 shut .. 1 open"), ("tongue", "0 in .. 1 out")):
        head.id_properties_ui(p).update(min=0.0, max=1.0, description=desc)

    # neck collar and the big lime throat plates running up under the chin
    cone("Head Collar", 1.5, 1.35, 1.8, M["armor"], coll, head, loc=(0, -1.2, 0.1), rot=(D(-90), 0, D(22.5)), segs=8, bevel=0.04)
    for k in range(4):
        w = 2.5 - 0.22 * k
        box(f"Head Throat Plate {k}", (w, 1.15, 0.32), M["lime"], coll, head, loc=(0, -1.6 + k * 1.05, -1.32 + k * 0.12),
            rot=(D(6), 0, 0), front=(0.82, 1), bevel=0.07)
    # skull: wide at the jaw hinge, a long tapering wedge to a blunt snout
    loft("Head Skull", [(-0.2, 1.45, 1.05, -0.35), (1.2, 1.62, 1.2, -0.42), (2.6, 1.45, 1.08, -0.4), (3.7, 1.05, 0.82, -0.36),
                        (4.5, 0.62, 0.52, -0.3), (4.9, 0.32, 0.3, -0.25)], M["armor"], coll, head, bevel=0.05)
    loft("Head Crest", [(0.0, 0.42, 1.38, 1.0), (2.2, 0.36, 1.32, 1.0), (3.9, 0.18, 0.95, 0.7)], M["dark"], coll, head, bevel=0.03)
    loft("Head Nose Plate", [(3.3, 0.7, 0.98, 0.7), (4.4, 0.45, 0.66, 0.42), (4.95, 0.26, 0.4, 0.2)], M["dark"], coll, head, bevel=0.03)
    for sx in (-1, 1):
        box(f"Head Brow {sx}", (0.5, 2.1, 0.42), M["dark"], coll, head, loc=(sx * 1.08, 2.75, 1.0),
            rot=(D(-6), sx * D(-18), sx * D(10)), front=(0.55, 0.45), bevel=0.05)
        box(f"Head Eye {sx}", (0.2, 1.1, 0.26), M["eye"], coll, head, loc=(sx * 1.36, 2.85, 0.68),
            rot=(0, sx * D(-20), sx * D(13)), front=(0.5, 0.35), bevel=0.0)
        box(f"Head Cheek Plate {sx}", (0.35, 2.6, 0.75), M["dark"], coll, head, loc=(sx * 1.5, 1.2, 0.15),
            rot=(0, 0, sx * D(4)), front=(0.6, 0.7), bevel=0.05)
        box(f"Head Cheek Glow {sx}", (0.08, 1.8, 0.1), M["glow"], coll, head, loc=(sx * 1.68, 1.2, -0.12),
            rot=(0, 0, sx * D(4)), bevel=0.0)
    for k, (sx, a) in enumerate(((0, 0), (-0.6, 28), (0.6, -28))):
        cone(f"Head Crown Spike {k}", 0.2, 0.0, 1.2, M["armor"], coll, head, loc=(sx, 0.3, 1.25), rot=(D(-62), D(a), 0), segs=6)
    # mouth: interior, upper fangs, a hinged lower jaw, a forked tongue
    loft("Head Mouth", [(0.4, 1.2, -0.3, -0.75), (3.6, 0.85, -0.3, -0.7), (4.5, 0.4, -0.25, -0.55)], M["mouth"], coll, head, bevel=0.0)
    for sx in (-1, 1):
        cone(f"Head Fang {sx}", 0.13, 0.0, 1.0, M["fang"], coll, head, loc=(sx * 0.42, 4.3, -0.3), rot=(D(180 - 10), 0, 0), segs=8)
    jaw = empty("Head Jaw Hinge", coll, head, loc=(0, 0.6, -0.42), size=0.4)
    loft("Head Jaw", [(0.0, 1.4, 0.15, -0.5), (1.9, 1.2, 0.12, -0.5), (3.1, 0.82, 0.08, -0.4), (3.9, 0.4, 0.05, -0.25)],
         M["armor"], coll, jaw, bevel=0.05)
    loft("Head Chin Plate", [(0.3, 1.0, -0.4, -0.62), (2.6, 0.8, -0.36, -0.56), (3.6, 0.38, -0.22, -0.36)], M["lime"], coll, jaw, bevel=0.03)
    for sx in (-1, 1):
        cone(f"Head Jaw Fang {sx}", 0.08, 0.0, 0.45, M["fang"], coll, jaw, loc=(sx * 0.45, 3.3, 0.05), rot=(D(-8), 0, 0), segs=6)
    drive(jaw, "rotation_euler", 0, "p * -0.6", head, "jaw")  # negative X swings the snout end down
    tongue = empty("Head Tongue Root", coll, jaw, loc=(0, 1.0, 0.1), size=0.3)
    box("Head Tongue", (0.18, 2.6, 0.06), M["tongue"], coll, tongue, loc=(0, 1.3, 0), bevel=0.0)
    for sx in (-1, 1):
        box(f"Head Tongue Fork {sx}", (0.1, 0.9, 0.05), M["tongue"], coll, tongue, loc=(sx * 0.17, 2.95, 0),
            rot=(0, 0, sx * D(-22)), bevel=0.0)
    drive(tongue, "scale", 1, "0.05 + p * 1.1", head, "tongue")
    build_hood(M, coll, head)
    light = bpy.data.lights.new("KESTREL Eye Light", "POINT")
    light.energy, light.color, light.shadow_soft_size = 250, (0.3, 1.0, 0.2), 1.0
    lo = bpy.data.objects.new("KESTREL | Eye light", light)
    coll.objects.link(lo)
    lo.parent, lo.location = head, (0, 4.5, 0.5)
    return head


# ---------------------------------------------------------------- build
def build(scene=None):
    """Create the KESTREL-9 collection in the scene; returns (body object, head empty)."""
    scene = scene or bpy.context.scene
    M = materials()
    root = bpy.data.collections.new("KESTREL-9")
    scene.collection.children.link(root)
    parts = bpy.data.collections.new("KESTREL | Parts (instanced)")
    root.children.link(parts)
    seg, spike, tail = build_parts(M, parts)
    g, ins = build_body_nodes(seg, spike, tail, M["glow"])
    body = bpy.data.objects.new("KESTREL | Body", bpy.data.meshes.new("KESTREL Body"))
    root.objects.link(body)
    mod = body.modifiers.new("Body", "NODES")
    mod.node_group = g
    head = build_head(M, root, body)
    # the instanced parts sit at the origin; keep them out of the render
    def exclude(lc):
        for c in lc.children:
            if c.collection == parts:
                c.exclude = True
            exclude(c)
    for vl in scene.view_layers:
        exclude(vl.layer_collection)
    return body, head


# ---------------------------------------------------------------- look-dev
def lookdev():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    body, head = build(scene)
    head["hood"], head["jaw"], head["tongue"] = 1.0, 0.7, 1.0
    world = bpy.data.worlds.new("Lookdev")
    scene.world = world
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.006, 0.02, 0.024, 1)
    for name, kind, loc, rot, energy, color, size in (
            ("Key", "AREA", (30, 40, 40), (D(35), D(30), D(120)), 120000, (0.85, 0.9, 1.0), 25),
            ("Rim", "AREA", (-35, 80, 10), (D(80), 0, D(-130)), 40000, (0.2, 1.0, 0.6), 20),
            ("Fill", "AREA", (10, 110, -10), (D(110), 0, D(170)), 8000, (1.0, 0.5, 0.2), 20)):
        ld = bpy.data.lights.new(name, kind)
        ld.energy, ld.color, ld.size = energy, color, size
        o = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(o)
        o.location, o.rotation_euler = loc, rot
    r = scene.render
    r.engine = "BLENDER_EEVEE"
    r.resolution_x, r.resolution_y = 1600, 900
    scene.eevee.taa_render_samples = 48
    scene.view_settings.view_transform = "AgX"
    comp = bpy.data.node_groups.new("Bloom", "CompositorNodeTree")
    comp.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl, gl, go = comp.nodes.new("CompositorNodeRLayers"), comp.nodes.new("CompositorNodeGlare"), comp.nodes.new("NodeGroupOutput")
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Threshold"].default_value, gl.inputs["Strength"].default_value, gl.inputs["Size"].default_value = 0.8, 0.6, 0.7
    comp.links.new(rl.outputs["Image"], gl.inputs["Image"])
    comp.links.new(gl.outputs["Image"], go.inputs[0])
    scene.compositing_node_group = comp
    r.use_compositing = True
    scene.frame_set(24)
    cams = []
    for name, loc, tgt, lens in (("full_side", (75, 25, 18), (0, 36, 0), 28),
                                 ("three_quarter", (28, 98, 9), (0, 52, 0), 24),
                                 ("head", (15, 86, 5), (0, 73, 0.5), 32)):
        cd = bpy.data.cameras.new(name)
        cd.lens, cd.clip_end = lens, 1000
        co = bpy.data.objects.new(name, cd)
        scene.collection.objects.link(co)
        co.location = loc
        co.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        cams.append(co)
    return scene, cams


if __name__ == "__main__" and "--lookdev" in ARGS:
    scene, cams = lookdev()
    if "--render" in ARGS:
        os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
        for c in cams:
            scene.camera = c
            scene.render.filepath = os.path.join(OUT, "renders", f"kestrel_{c.name}.png")
            bpy.ops.render.render(write_still=True)
        # the cruising pose: hood folded, mouth shut
        head = bpy.data.objects["KESTREL | Head"]
        head["hood"], head["jaw"], head["tongue"] = 0.0, 0.0, 0.0
        scene.frame_set(scene.frame_current)
        scene.camera = cams[-1]
        scene.render.filepath = os.path.join(OUT, "renders", "kestrel_head_folded.png")
        bpy.ops.render.render(write_still=True)
        head["hood"], head["jaw"], head["tongue"] = 1.0, 0.7, 1.0
    if "--save" in ARGS:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "kestrel_lookdev.blend"))
        print("SAVED kestrel_lookdev.blend")

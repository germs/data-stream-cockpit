"""Append the cockpit from cockpit_dash.blend into the open scene and lock it to the flight camera.

Run on the terrain file:
  Blender --background --enable-autoexec data_stream_sparks_restored.blend --python place_cockpit.py -- \
      [--eye Y Z] [--pitch DEG] [--bloom THRESHOLD STRENGTH SIZE] [--render 1,300,600] [--percent 50] [--save]

--eye is the pilot's eye position in cockpit space (cockpit faces +Y, Z up); --pitch tilts the
cockpit relative to the camera (positive lowers the dash in frame).
"""
import bpy, math, os, sys
from mathutils import Euler, Vector

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, n=1, default=None):
    if name not in ARGS:
        return default
    i = ARGS.index(name)
    vals = ARGS[i + 1:i + 1 + n]
    return vals[0] if n == 1 else vals


EYE = Vector((0.0, *map(float, arg("--eye", 2, ("-0.69", "1.3")))))
PITCH = math.radians(float(arg("--pitch", 1, "0")))
SKIP = {"Pilot View", "Overview", "Starlight"}  # cockpit-only cameras, and a sun that would light the terrain

scene = bpy.context.scene
cam = scene.camera

# Append every cockpit object except the skipped ones into a dedicated collection.
src = os.path.join(OUT, "cockpit_dash.blend")
with bpy.data.libraries.load(src, link=False) as (data_from, data_to):
    data_to.objects = [n for n in data_from.objects if n not in SKIP]

coll = bpy.data.collections.new("COCKPIT")
scene.collection.children.link(coll)
for o in data_to.objects:
    coll.objects.link(o)

# Rig: maps cockpit space onto camera space (cockpit +Y -> camera -Z, cockpit +Z -> camera +Y)
# with the pilot's eye sitting exactly on the camera.
rig = bpy.data.objects.new("COCKPIT | Rig", None)
rig.empty_display_type = "ARROWS"
rig.empty_display_size = 0.3
coll.objects.link(rig)
rot = Euler((-math.pi / 2 + PITCH, 0, 0))
rig.parent = cam
rig.rotation_euler = rot
rig.location = -(rot.to_matrix() @ EYE)
for o in data_to.objects:
    if o.parent is None:
        o.parent = rig

print("COCKPIT objects", len(data_to.objects), "eye", tuple(EYE), "pitch", math.degrees(PITCH))

# Bloom: Render Layers -> Glare (Bloom) -> output, as the scene's compositor.
threshold, strength, size = map(float, arg("--bloom", 3, ("0.3", "0.7", "0.75")))
comp = bpy.data.node_groups.new("Bloom", "CompositorNodeTree")
comp.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
rl = comp.nodes.new("CompositorNodeRLayers")
gl = comp.nodes.new("CompositorNodeGlare")
gl.inputs["Type"].default_value = "Bloom"
gl.inputs["Quality"].default_value = "High"
gl.inputs["Threshold"].default_value = threshold
gl.inputs["Strength"].default_value = strength
gl.inputs["Size"].default_value = size
go = comp.nodes.new("NodeGroupOutput")
rl.location, gl.location, go.location = (-300, 0), (0, 0), (300, 0)
comp.links.new(rl.outputs["Image"], gl.inputs["Image"])
comp.links.new(gl.outputs["Image"], go.inputs[0])
scene.compositing_node_group = comp
scene.render.use_compositing = True
print("BLOOM", threshold, strength, size)

# The source file carries a Windows output path; write the video next to the .blend instead.
scene.render.filepath = "//renders/data_stream_cockpit.mp4"

frames = arg("--render")
if frames:
    pct = int(arg("--percent", 1, "50"))
    r = scene.render
    saved = (r.resolution_percentage, r.filepath)
    img = r.image_settings
    saved_fmt = (getattr(img, "media_type", None), img.file_format)
    if saved_fmt[0] is not None:
        img.media_type = "IMAGE"
    img.file_format = "PNG"
    r.resolution_percentage = pct
    os.makedirs(os.path.join(OUT, "renders"), exist_ok=True)
    for f in map(int, frames.split(",")):
        scene.frame_set(f)
        r.filepath = os.path.join(OUT, "renders", f"cockpit_flight_f{f:04d}.png")
        bpy.ops.render.render(write_still=True)
    r.resolution_percentage, r.filepath = saved
    if saved_fmt[0] is not None:
        img.media_type = saved_fmt[0]
    img.file_format = saved_fmt[1]

if "--save" in ARGS:
    scene.frame_set(scene.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "data_stream_cockpit.blend"), copy=True)
    print("SAVED")

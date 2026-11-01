"""Final-delivery render settings: EEVEE, 1920x1080 @ 24 fps, 128 samples, PNG sequence to renders/final/.

Run on the finale file:
  Blender --background data_stream_cockpit_finale.blend --python final_render_settings.py -- \
      [--test 441,630,700] [--save data_stream_final.blend]
--test renders those frames at full quality to renders/final_test/ and prints the time each took.
Render the whole sequence afterwards with:
  Blender -b data_stream_final.blend -a
"""
import bpy, os, sys, time

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


scene = bpy.context.scene
r = scene.render
r.engine = "BLENDER_EEVEE"
r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
r.fps, r.fps_base = 24, 1.0
scene.eevee.taa_render_samples = 128
scene.eevee.use_raytracing = True
r.use_motion_blur = True
r.motion_blur_shutter = 0.5
r.use_compositing = True
scene.view_settings.view_transform = "AgX"
img = r.image_settings
if hasattr(img, "media_type"):
    img.media_type = "IMAGE"
img.file_format = "PNG"
img.color_mode = "RGB"
img.color_depth = "8"
img.compression = 15
r.filepath = "//renders/final/frame_####"
r.use_file_extension = True
r.use_overwrite = False      # a restarted render skips frames already on disk
r.use_placeholder = True     # several machines/processes can share the sequence

print(f"FINAL SETTINGS {r.resolution_x}x{r.resolution_y} {r.fps}fps samples={scene.eevee.taa_render_samples} "
      f"mblur={r.use_motion_blur} look={scene.view_settings.look} frames {scene.frame_start}-{scene.frame_end} -> {r.filepath}")

frames = arg("--test")
if frames:
    os.makedirs(os.path.join(OUT, "renders", "final_test"), exist_ok=True)
    keep = r.filepath
    for f in map(int, frames.split(",")):
        scene.frame_set(f)
        r.filepath = os.path.join(OUT, "renders", "final_test", f"test_f{f:04d}.png")
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"TIMED frame {f} ({scene.camera.name}): {time.time() - t:.1f} s")
    r.filepath = keep

if arg("--save"):
    scene.frame_set(scene.frame_start)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, arg("--save")), copy=True)
    print("SAVED", arg("--save"))

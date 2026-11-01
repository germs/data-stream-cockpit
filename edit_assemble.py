"""Assemble the final video in Blender's Video Sequencer: the rendered PNG frames + the synth stems -> MP4 (H.264 + AAC).

Builds data_stream_edit.blend (open it to re-balance stems or nudge strips) and encodes data_stream_final.mp4.
  Blender --background --factory-startup --python edit_assemble.py -- [--frames 680] [--no-encode]
Channels: 1 picture, 2 engine, 3 hud, 4 creature, 5 warp. Each stem's volume is its strip's Volume.
"""
import bpy, glob, os, sys

OUT = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
NF = int(ARGS[ARGS.index("--frames") + 1]) if "--frames" in ARGS else 680

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "EDIT"
r = scene.render
r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
r.fps, r.fps_base = 24, 1.0
scene.frame_start, scene.frame_end = 1, NF
# the frames already carry the AgX look; show them untouched
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.sequencer_colorspace_settings.name = "sRGB"

frames = sorted(glob.glob(os.path.join(OUT, "renders", "final", "frame_*.png")))[:NF]
assert len(frames) == NF and all(os.path.getsize(f) > 0 for f in frames), f"expected {NF} complete frames, found {len(frames)}"
se = scene.sequence_editor_create()
coll = se.strips if hasattr(se, "strips") else se.sequences
pic = coll.new_image("PICTURE", frames[0], 1, 1)
for f in frames[1:]:
    pic.elements.append(os.path.basename(f))
for ch, stem in enumerate(("engine", "hud", "creature", "warp"), start=2):
    s = coll.new_sound(stem.upper(), os.path.join(OUT, "audio", f"stem_{stem}.wav"), ch, 1)
    s.volume = 1.0
print("EDIT strips:", [(s.name, s.channel, s.frame_final_start, s.frame_final_end) for s in coll])

img = r.image_settings
if hasattr(img, "media_type"):
    img.media_type = "VIDEO"
img.file_format = "FFMPEG"
ff = r.ffmpeg
ff.format, ff.codec = "MPEG4", "H264"
ff.constant_rate_factor = "HIGH"
ff.ffmpeg_preset = "BEST"
ff.gopsize = 24
ff.audio_codec, ff.audio_bitrate, ff.audio_mixrate, ff.audio_channels = "AAC", 320, 48000, "STEREO"
r.use_sequencer = True
r.use_compositing = False
r.filepath = os.path.join(OUT, "renders", "video", "data_stream_final_")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "data_stream_edit.blend"))
print("SAVED data_stream_edit.blend")

if "--no-encode" not in ARGS:
    os.makedirs(os.path.join(OUT, "renders", "video"), exist_ok=True)
    bpy.ops.render.render(animation=True)
    made = sorted(glob.glob(os.path.join(OUT, "renders", "video", "data_stream_final_*.mp4")), key=os.path.getmtime)
    print("ENCODED", made[-1] if made else "nothing found")

# Data Stream Cockpit

A 30-second first-person flight through a glowing data valley, built procedurally in Blender 5.x with Python:
a cockpit with live HUD screens and holograms, a 70 m flying mechanical cobra (KESTREL-9) that the ship
locks onto, and a warp-jump finale, plus a synthesized temp soundtrack and an automated edit.

Everything renders without Python at render time: animation is keyframes, simple drivers and Geometry Nodes,
so the `.blend` files work on any machine or render farm.

## Pipeline

Each script is run headless on the previous stage's file and writes a new one, so every stage can be re-run.

| # | Script | Runs on | Produces | What it does |
|---|--------|---------|----------|--------------|
| 1 | `cockpit_dash.py` | (empty) | `cockpit_dash.blend` | Builds the procedural cockpit dash, screens, holograms, lights |
| 2 | `place_cockpit.py` | terrain scene | `data_stream_cockpit.blend` | Appends the cockpit and locks it to the flight camera; bloom compositor |
| 3 | `cockpit_flight_motion.py` | `data_stream_cockpit.blend` | `data_stream_cockpit_flight.blend` | Cockpit body with bank, turbulence (scaled by speed) and pilot head motion |
| 4 | `cockpit_hud_animation.py` | flight file | `data_stream_cockpit_hud.blend` | Boot-up, live readouts (Geometry Nodes text), alerts, lock-on, glitches |
| 5 | `creature_kestrel.py` | (library / look-dev) | `kestrel_lookdev.blend` | KESTREL-9: GN-swum armoured body, faceted head, fold/flare hood |
| 6 | `place_kestrel.py` | HUD file | `data_stream_cockpit_kestrel.blend` | Stages the creature as the HUD's contact: overtake, turn, close pass at the lock |
| 7 | `warp_finale.py` | creature file | `data_stream_cockpit_finale.blend` | Extends to 720 frames: jump spool, creature cameo, warp jump, hyperspace, title |
| 8 | `final_render_settings.py` | finale file | `data_stream_final.blend` | EEVEE 1920x1080 @ 24 fps, 128 samples, PNG sequence; times test frames |
| 9 | `audio_synth.py` | final file | `audio/*.wav` | Synth stems driven by the animation (speed, turbulence, creature position) |
| 10 | `edit_assemble.py` | (empty) | `data_stream_edit.blend`, MP4 | Sequencer edit: frames + stems -> H.264/AAC |

Typical call:

```
blender --background data_stream_cockpit_hud.blend --python place_kestrel.py -- --render 205,441 --save data_stream_cockpit_kestrel.blend
```

Most scripts accept `--render f1,f2,...` (check frames to `renders/`) and `--save NAME.blend`.

## Timeline (24 fps)

| Frames | Beat |
|--------|------|
| 1-143 | Slow glide - cockpit boots, holograms appear |
| 144-359 | Gathering speed - KESTREL-9 contact at 200 |
| 360-503 | Acceleration - CORE BOOST, lance charges, creature turns on us, lock at 440 |
| 504-559 | Maximum velocity |
| 560-609 | Jump spool - countdown, creature lunges |
| 610 | Jump |
| 612-659 | Hyperspace |
| 660-683 | Exit - white-out |
| 684-720 | Title card |

## Not in the repo

The `.blend` scenes (~250 MB each), renders and audio are generated and kept out of Git (see `.gitignore`).
The terrain scene that `place_cockpit.py` starts from is not included.

## Requirements

Blender 5.2+ (uses the 5.x Geometry Nodes modifier, compositor node group and layered-action APIs).

"""Run inside Blender to verify the upstream timeline and camera changes."""
import json
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root/'vendor/animations/Plantilla.blend'))
results = {}
for name, seconds, marker_count in [('01_PREPARTIDO_13s', 13, 8), ('02_VICTORIA_2s', 4, 4)]:
    scene = bpy.data.scenes[name]
    actual = (scene.frame_end-scene.frame_start+1)*scene.render.fps_base/scene.render.fps
    assert abs(actual-seconds) < .001, (name, actual)
    assert len(scene.timeline_markers) == marker_count, name
    assert abs(scene.camera.data.lens-37) < .001, name
    scene.frame_set(scene.frame_start)
    first = tuple(scene.camera.location)
    scene.frame_set(scene.frame_end)
    last = tuple(scene.camera.location)
    results[name] = dict(duration=actual, frames=scene.frame_end-scene.frame_start+1,
                         first=first, last=last, markers=[m.name for m in scene.timeline_markers])
    if seconds == 13:
        assert max(abs(a-b) for a,b in zip(first, last)) < .001
    else:
        assert first[0] < 0 < last[0]
print('TEMPLATE_QA:'+json.dumps(results), flush=True)

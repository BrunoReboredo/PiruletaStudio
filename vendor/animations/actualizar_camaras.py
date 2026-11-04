"""Recorridos editables de cámara. Ejecutar con Blender --python y archivos tras --."""
import sys
from pathlib import Path
import bpy
from mathutils import Vector


def animate(scene, keys, duration):
    camera = scene.camera
    camera.animation_data_clear()
    camera.data.animation_data_clear()
    camera.rotation_mode = 'XYZ'
    camera.data.lens = 37
    previous = None
    scene.frame_start = 1
    scene.frame_end = round(duration * scene.render.fps / scene.render.fps_base)
    scene.timeline_markers.clear()
    for seconds, position, target, label in keys:
        frame = min(scene.frame_end, round(seconds * scene.render.fps / scene.render.fps_base) + 1)
        camera.location = position
        quaternion = (Vector(target) - camera.location).to_track_quat('-Z', 'Y')
        rotation = quaternion.to_euler('XYZ', previous) if previous else quaternion.to_euler('XYZ')
        camera.rotation_euler = rotation
        previous = rotation.copy()
        camera.keyframe_insert(data_path='location', frame=frame)
        camera.keyframe_insert(data_path='rotation_euler', frame=frame)
        scene.timeline_markers.new(label, frame=frame)
    for curve in camera.animation_data.action.fcurves:
        for point in curve.keyframe_points:
            point.interpolation = 'BEZIER'
            point.handle_left_type = 'AUTO_CLAMPED'
            point.handle_right_type = 'AUTO_CLAMPED'
    scene['Duracion'] = f'{duration} segundos'
    scene['Camara | recorrido'] = ' / '.join(key[3] for key in keys)
    scene.frame_set(1)


def update():
    animate(bpy.data.scenes['01_PREPARTIDO_13s'], [
        (0, (0, -24, 6.2), (0, 1.5, 3.3), 'INICIO | Plano abierto'),
        (2.2, (-2.4, -17, 4.5), (-2, .5, 2.4), 'ACERCAMIENTO'),
        (4.3, (-7, -8.8, 3.2), (-4.3, -.1, 1.5), 'COCHE A'),
        (5.1, (-6.6, -8.4, 3.1), (-4.3, -.1, 1.5), 'GIRO RAPIDO | Salida A'),
        (6.1, (6.6, -8.4, 3.1), (4.3, -.1, 1.5), 'GIRO RAPIDO | Llegada B'),
        (7.3, (7, -8.8, 3.2), (4.3, -.1, 1.5), 'COCHE B'),
        (9.4, (0, -16.5, 4.8), (0, 1.5, 3.3), 'CENTRO'),
        (13, (0, -24, 6.2), (0, 1.5, 3.3), 'FIN | Plano inicial'),
    ], 13)
    # Identificador conservado para compatibilidad con los editores existentes.
    animate(bpy.data.scenes['02_VICTORIA_2s'], [
        (0, (-8, -22, 6), (0, 1.2, 3.1), 'INICIO | Abierto izquierda'),
        (.8, (-7, -21, 5.6), (0, 1.2, 3.1), 'ANTICIPACION'),
        (2.5, (6.5, -19.5, 5), (0, 1.2, 3.1), 'GIRO | Barrido derecha'),
        (4, (8, -20.5, 5.4), (0, 1.2, 3.1), 'FIN | Victoria'),
    ], 4)


if __name__ == '__main__':
    bpy.context.preferences.filepaths.save_version = 0
    for filename in sys.argv[sys.argv.index('--') + 1:]:
        path = str(Path(filename).resolve())
        bpy.ops.wm.open_mainfile(filepath=path)
        update()
        bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
        print('CAMARAS_ACTUALIZADAS', path, flush=True)


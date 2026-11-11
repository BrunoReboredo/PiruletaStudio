"""Worker executed by Blender, never by the desktop Python runtime."""
import bpy
import json
import math
import os
import sys
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paint_finishes import apply_finish


def announce(message):
    print('RLCS_STATUS:' + message, flush=True)


def image_file(path, work, part='body'):
    path = Path(path)
    if path.suffix.lower() != '.zip':
        return str(path) if part == 'body' else None
    with zipfile.ZipFile(path) as archive:
        entries = [n for n in archive.namelist() if not n.endswith('/')]
        images = [n for n in entries if Path(n).suffix.lower() in ('.png', '.jpg', '.jpeg', '.tga', '.dds')]
        selected = None
        for entry in entries:
            if not entry.lower().endswith('.json'):
                continue
            try:
                if archive.getinfo(entry).file_size > 1_000_000:
                    continue
                raw = archive.read(entry)
                if len(raw) > 1_000_000:
                    continue
                package = json.loads(raw.decode('utf-8-sig'))
                for spec in package.values():
                    section = spec.get('Body' if part == 'body' else 'Chassis', {})
                    wanted = section.get('1_Diffuse_Skin') or section.get('Diffuse')
                    if wanted:
                        selected = next((n for n in images if Path(n).name.casefold() == Path(wanted).name.casefold()), None)
                        if selected:
                            break
            except (ValueError, AttributeError, UnicodeError):
                continue
            if selected:
                break
        if not selected:
            if part == 'chassis':
                selected = next((n for n in images if 'chassis' in n.lower()), None)
            else:
                selected = next((n for n in images if not any(x in Path(n).name.lower() for x in ('mask', 'chassis', 'truco', 'logo'))), None)
        if not selected:
            if part == 'body':
                raise ValueError('El ZIP no contiene una calcomanía reconocible.')
            return None
        info = archive.getinfo(selected)
        if info.file_size > 100_000_000:
            raise ValueError('La imagen del ZIP supera los 100 MB.')
        target = work / (part + Path(selected).suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(selected))
        return str(target)


def load_image(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    image.pack()
    return image


def fit_logo(obj, image):
    import numpy as np
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    alpha = pixels.reshape(height, width, 4)[:, :, 3]
    ys, xs = np.where(alpha > .02)
    if len(xs):
        x0, x1 = max(0, int(xs.min())-2), min(width, int(xs.max())+3)
        y0, y1 = max(0, int(ys.min())-2), min(height, int(ys.max())+3)
    else:
        x0, y0, x1, y1 = 0, 0, width, height
    uv = obj.data.uv_layers.active
    if uv and len(obj.data.vertices) == 4:
        coords = [(x0/width, y0/height), (x1/width, y0/height), (x1/width, y1/height), (x0/width, y1/height)]
        for loop in obj.data.loops:
            uv.data[loop.index].uv = coords[loop.vertex_index]
        aspect = (x1-x0) / max(y1-y0, 1)
        for vertex in obj.data.vertices:
            vertex.co.x = (1 if vertex.co.x > 0 else -1) * 1.18 * min(aspect, 1.35)
            vertex.co.z = (1 if vertex.co.z > 0 else -1) * 1.18 / max(1, aspect/1.35)


def illuminate_logo(obj):
    """Make screen crests self-lit while preserving their image and alpha mask."""
    for material in obj.data.materials:
        if not material.use_nodes:
            continue
        material['logo_emission_strength'] = 2.0
        for node in material.node_tree.nodes:
            if node.type == 'EMISSION':
                node.inputs['Strength'].default_value = 2.0
                node.label = 'Luminosidad del escudo · editable'
            elif node.type == 'BSDF_PRINCIPLED':
                texture = next((n for n in material.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
                if texture:
                    material.node_tree.links.new(texture.outputs['Color'], node.inputs['Emission Color'])
                node.inputs['Emission Strength'].default_value = 2.0


def remove_template_cars():
    for collection in list(bpy.data.collections):
        if collection.name.startswith(('06 |', 'GANADOR A', 'GANADOR B', 'AUTO |')):
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(collection)


def add_team_car(scene, anchor, team, settings, folder, finish='Brillante'):
    model = settings.get('car', 'Octane' if team == 'A' else 'Fennec')
    if model not in ('Octane', 'Fennec', 'Dominus'):
        raise ValueError('Modelo de coche desconocido: ' + str(model))
    library = Path(__file__).resolve().parent / 'models.blend'
    with bpy.data.libraries.load(str(library), link=False) as (source, target):
        target.collections = ['CAR_' + model]
    collection = target.collections[0]
    if not collection:
        raise ValueError('No se encuentra el modelo ' + model + ' en la biblioteca.')
    collection.name = 'AUTO | ' + team + ' | ' + model
    collection['rlcs_team'] = team
    collection['rlcs_model'] = model
    scene.collection.children.link(collection)
    root = next(o for o in collection.objects if o.get('rlcs_root'))
    root.parent = anchor
    if scene.get('arena_revision', 0) >= 2:
        root.scale *= 1.25
        root.location *= 1.25
    root['rlcs_team'] = team
    root['rlcs_model'] = model
    body = chassis = None
    if settings.get('skin'):
        body = load_image(image_file(settings['skin'], folder / ('textures_' + team)))
        chassis_path = image_file(settings['skin'], folder / ('textures_' + team), 'chassis')
        if chassis_path:
            chassis = load_image(chassis_path)
    materials = {}
    for obj in collection.objects:
        if obj.type != 'MESH':
            continue
        for i, original in enumerate(list(obj.data.materials)):
            role = original.get('rlcs_role')
            if not role:
                continue
            if original not in materials:
                material = original.copy()
                material.name = 'EQUIPO_' + team + ' | ' + model + ' | ' + role
                material['rlcs_team'] = team
                material['rlcs_custom_skin'] = bool(body)
                p = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
                texture = chassis if role == 'chassis' else body
                if role == 'paint':
                    # Painted body variant: black trim, independent of team paint/decal.
                    for link in list(p.inputs['Base Color'].links):
                        material.node_tree.links.remove(link)
                    p.inputs['Base Color'].default_value = (.004, .004, .004, 1)
                    material.diffuse_color = (.004, .004, .004, 1)
                    p.inputs['Metallic'].default_value = .25
                    p.inputs['Roughness'].default_value = .3
                    p.inputs['Emission Strength'].default_value = 0
                    material['rlcs_painted_variant'] = 'Black'
                elif role == 'body' or texture:
                    for link in list(p.inputs['Base Color'].links):
                        material.node_tree.links.remove(link)
                    if texture:
                        node = material.node_tree.nodes.new('ShaderNodeTexImage')
                        node.name = 'SKIN | Editable'
                        node.image = texture
                        uv = material.node_tree.nodes.new('ShaderNodeUVMap')
                        uv.uv_map = original.get('rlcs_uv', 'UVMap')
                        if role != 'chassis':
                            flip = material.node_tree.nodes.new('ShaderNodeVectorMath')
                            flip.name = 'Orientacion textura del juego'
                            flip.operation = 'MULTIPLY_ADD'
                            flip.inputs[1].default_value = (1, -1, 1)
                            flip.inputs[2].default_value = (0, 1, 0)
                            material.node_tree.links.new(uv.outputs[0], flip.inputs[0])
                            material.node_tree.links.new(flip.outputs[0], node.inputs['Vector'])
                        else:
                            material.node_tree.links.new(uv.outputs[0], node.inputs['Vector'])
                        material.node_tree.links.new(node.outputs['Color'], p.inputs['Base Color'])
                    else:
                        p.inputs['Base Color'].default_value = (*rgb(settings['color']), 1)
                    if role in ('body', 'paint'):
                        material.diffuse_color = (*rgb(settings['color']), 1) if not body else (1, 1, 1, 1)
                        p.inputs['Emission Strength'].default_value = 0
                        p.inputs['Metallic'].default_value = .35
                        p.inputs['Roughness'].default_value = .32
                if role == 'body':
                    apply_finish(material, finish, custom_skin=bool(settings.get('skin')))
                materials[original] = material
            obj.data.materials[i] = materials[original]
    return collection


def copy_winner_car(source, victory, anchor):
    collection = bpy.data.collections.new('AUTO | GANADOR | ' + source['rlcs_model'])
    collection['rlcs_team'] = source['rlcs_team']
    collection['rlcs_model'] = source['rlcs_model']
    victory.collection.children.link(collection)
    copies = {}
    for old in source.objects:
        obj = old.copy()
        collection.objects.link(obj)
        copies[old] = obj
    for old, obj in copies.items():
        if old.get('rlcs_root'):
            obj.parent = anchor
        elif old.parent in copies:
            obj.parent = copies[old.parent]
    return collection


def set_text(names, value):
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj and obj.type == 'FONT':
            obj.data.body = value
            # Avoid overflow on long names while retaining the template typography.
            obj.data.size *= min(1, 21 / max(len(value), 1))


def color_material(material, color):
    material.diffuse_color = (*color, 1)
    p = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if p:
        p.inputs['Base Color'].default_value = (*color, 1)
        p.inputs['Emission Color'].default_value = (*color, 1)
    for node in material.node_tree.nodes:
        if node.type == 'EMISSION':
            node.inputs['Color'].default_value = (*color, 1)


def rgb(hex_value):
    # Convert UI sRGB values to Blender linear values.
    values = [int(hex_value.lstrip('#')[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values)


def enable_object(obj, visible):
    obj.hide_render = not visible
    obj.hide_viewport = not visible
    for scene in bpy.data.scenes:
        for layer in scene.view_layers:
            if obj.name in layer.objects:
                obj.hide_set(not visible, view_layer=layer)


def position_pre_names(scene):
    """Put readable white names between each crest and car, never above the crest."""
    for team, x in (('A', -4.8), ('B', 4.8)):
        obj = bpy.data.objects.get('NOMBRE | Equipo '+team)
        if not obj:
            continue
        obj.location = (x, -8.5 + math.sqrt(196-x*x) - .26, 3.7) if scene.get('arena_revision') else (x, 1.2, 4.05)
        obj.data.align_x = 'CENTER'
        obj.data.align_y = 'CENTER'
        obj.data.size = 0.46
        bpy.context.view_layer.update()
        width = obj.dimensions.x
        if width > 7.8:
            obj.data.size *= 7.8 / width



def configure(config, folder):
    remove_template_cars()
    for obj in bpy.data.objects:
        if obj.name.startswith('EMBLEMA | Sustituible'):
            enable_object(obj, False)
    pre = bpy.data.scenes['01_PREPARTIDO_13s']
    cars = {}
    logo_materials = {}
    for team in ('A', 'B'):
        settings = config['teams'][team]
        announce('Personalizando equipo ' + team)
        set_text(['NOMBRE | Equipo ' + team, 'TEXTO | Equipo MCI' if team == 'A' else 'TEXTO | Equipo NIP',
                  'TEXTO | Equipo Portal Draco' if team == 'A' else ''], settings['name'])
        set_text(['ABREVIATURA | ' + team, 'TEXTO | Emblema MCI' if team == 'A' else 'TEXTO | Emblema NIP'], settings['short'])
        set_text(['NOMBRE | Placa ' + team, 'TEXTO | Jugador 1' if team == 'A' else 'TEXTO | Jugador 2'], settings['short'] + ' | ' + settings['name'])
        color_material(bpy.data.materials['TEAM_' + team + ' | Color editable'], rgb(settings['color']))
        for arena_material in bpy.data.materials:
            if arena_material.get('arena_team') == team:
                gain = arena_material.get('arena_gain', 1)
                color_material(arena_material, tuple(v*gain for v in rgb(settings['color'])))
        cars[team] = add_team_car(pre, bpy.data.objects['EQUIPO_' + team + ' | ANCLA'], team, settings, folder, config.get('paint_finish', 'Brillante'))
        logo_objects = [o for o in bpy.data.objects if o.type == 'MESH' and
                        (o.name.startswith('ESCUDO | ' + team + ' ') or o.name == 'LOGO | ' + ('PD' if team == 'A' else 'GOAT'))]
        if settings.get('logo'):
            logo_image = load_image(settings['logo'])
            for obj in logo_objects:
                fit_logo(obj, logo_image)
                for material in obj.data.materials:
                    for node in material.node_tree.nodes:
                        if node.type == 'TEX_IMAGE':
                            node.image = logo_image
                enable_object(obj, True)
        # A missing logo leaves the generic abbreviation visible.
        for obj in logo_objects:
            illuminate_logo(obj)
            if obj.data.materials:
                logo_materials[team] = (obj.data.materials[0], not obj.hide_render)
        if any(not o.hide_render for o in logo_objects):
            for name in ['ABREVIATURA | ' + team, 'TEXTO | Emblema MCI' if team == 'A' else 'TEXTO | Emblema NIP']:
                obj = bpy.data.objects.get(name)
                if obj:
                    enable_object(obj, False)

    position_pre_names(pre)
    winner = config['winner']
    settings = config['teams'][winner]
    set_text(['NOMBRE | Ganador', 'TEXTO | Equipo ganador'], settings['name'])
    set_text(['NOMBRE | Placa ganador', 'TEXTO | Jugador 1.001'], settings['short'] + ' | ' + settings['name'])
    set_text(['TEXTO | Cabecera'], config.get('victory_header', 'ROCKET LEAGUE COMPETITIVE'))
    victory = bpy.data.scenes['02_VICTORIA_2s']
    copy_winner_car(cars[winner], victory, bpy.data.objects['GANADOR | ANCLA'])
    material = bpy.data.materials['TEAM_' + winner + ' | Color editable']
    for obj in victory.objects:
        if obj.name.startswith('ARENA |') and obj.type in ('MESH', 'CURVE'):
            for index, arena_material in enumerate(obj.data.materials):
                if arena_material.get('arena_team'):
                    stem = arena_material.name.rsplit(' ', 1)[0]
                    obj.data.materials[index] = bpy.data.materials[stem+' '+winner]
    for obj in victory.objects:
        if obj.type == 'MESH' and obj.name.startswith(('PANTALLA | Ganador', 'PANTALLA | Banda titulo', 'PLATAFORMA | Aro LED')):
            obj.data.materials.clear()
            obj.data.materials.append(material)
        if obj.type == 'MESH' and obj.name.startswith(('ESCUDO | Ganador', 'LOGO | GOAT victoria')):
            if winner in logo_materials:
                logo_material, visible = logo_materials[winner]
                obj.data.materials.clear()
                obj.data.materials.append(logo_material)
                node = next((n for n in logo_material.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image), None)
                if node:
                    fit_logo(obj, node.image)
                enable_object(obj, visible)
    pattern = bpy.data.materials.get('SCREEN | Patron victoria')
    if pattern:
        color_material(pattern, tuple(v * .24 for v in rgb(settings['color'])))
    for scene in bpy.data.scenes:
        scene.frame_set(1)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.type = 'MATERIAL'
                space.shading.use_scene_lights = True
                space.shading.use_scene_world = True
                space.overlay.show_overlays = False
                space.region_3d.view_perspective = 'CAMERA'
    bpy.context.window.scene = bpy.data.scenes['01_PREPARTIDO_13s']
    credits_path = Path(__file__).resolve().parent / 'CREDITOS.txt'
    if credits_path.is_file():
        credits = bpy.data.texts.get('CREDITOS | Modelos') or bpy.data.texts.new('CREDITOS | Modelos')
        credits.clear()
        credits.write(credits_path.read_text(encoding='utf-8-sig'))
    bpy.ops.file.pack_all()


def main(job):
    config = json.loads(Path(job).read_text(encoding='utf-8'))
    folder = Path(config['output'])
    folder.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=config['template'])
    bpy.context.preferences.filepaths.save_version = 0
    configure(config, folder)
    engine = config.get('engine', 'CYCLES')
    if engine not in ('EEVEE', 'CYCLES'):
        raise ValueError('Motor de render no compatible: '+str(engine))
    for scene in bpy.data.scenes:
        scene.render.engine = 'BLENDER_EEVEE_NEXT' if engine == 'EEVEE' else 'CYCLES'
        if engine == 'EEVEE':
            scene.eevee.taa_render_samples = config.get('samples', 32)
            scene.eevee.use_raytracing = False
    for _ in range(3):
        bpy.data.orphans_purge(do_recursive=True)
    blend = folder / 'Partido.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)
    (folder / 'proyecto.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    for scene_name, basename, frame in [('01_PREPARTIDO_13s', 'Prepartido', 300), ('02_VICTORIA_2s', 'Victoria', 1)]:
        if config.get('only_scenes') and basename not in config['only_scenes']:
            continue
        if config.get('only_victory') and basename == 'Prepartido':
            continue
        scene = bpy.data.scenes[scene_name]
        bpy.context.window.scene = scene
        scene.frame_set(frame)
        scene.render.resolution_percentage = config.get('preview_resolution', 50)
        scene.cycles.samples = config.get('samples', 16)
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = str(folder / (basename + '.png'))
        announce('Generando vista previa: ' + basename+' · '+engine)
        bpy.ops.render.render(write_still=True)
        if config.get('video') and basename not in config.get('cached_videos', []):
            announce('Exportando vídeo: ' + basename + '. Puede tardar varios minutos.')
            scene.render.resolution_percentage = config.get('resolution', 100)
            scene.cycles.samples = config.get('samples', 24)
            scene.render.image_settings.file_format = 'FFMPEG'
            scene.render.ffmpeg.format = 'MPEG4'
            scene.render.ffmpeg.codec = 'H264'
            scene.render.ffmpeg.constant_rate_factor = 'HIGH'
            scene.render.filepath = str(folder / (basename + '.mp4'))
            if config.get('test_frames'):
                scene.frame_end = scene.frame_start + config['test_frames'] - 1
            bpy.ops.render.render(animation=True)
    announce('Listo. Archivos guardados en ' + str(folder))
    (folder / 'completado.json').write_text(json.dumps({'blend': str(blend), 'video': bool(config.get('video'))}), encoding='utf-8')


if __name__ == '__main__':
    try:
        main(sys.argv[sys.argv.index('--') + 1])
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

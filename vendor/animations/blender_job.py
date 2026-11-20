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

RING_LIGHT_COUNT = 16


def remove_legacy_elements():
    prefixes = ('NOMBRE | Placa', 'Foco visible', 'ARENA | Borde ', 'ARENA | Remate ',
                'SCREEN | Chevron', 'PANTALLA | Banda titulo', 'EMBLEMA | Sustituible')
    for obj in list(bpy.data.objects):
        if obj.name.startswith(prefixes):
            bpy.data.objects.remove(obj, do_unlink=True)


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



def align_team_graphics():
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    previous_scene = bpy.context.window.scene
    for scene in bpy.data.scenes:
        victory = scene.name.startswith('02_')
        previous_frame = scene.frame_current
        bpy.context.window.scene = scene
        scene.frame_set(1 if victory else 300)
        scene.view_layers[0].update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        camera = scene.camera.evaluated_get(depsgraph)
        teams = [('Ganador', 'GANADOR | ANCLA')] if victory else [('A', 'EQUIPO_A | ANCLA'), ('B', 'EQUIPO_B | ANCLA')]
        for team, anchor_name in teams:
            anchor = bpy.data.objects[anchor_name]
            center = anchor.evaluated_get(depsgraph).matrix_world.translation + Vector((0, 0, .85))
            target_x = world_to_camera_view(scene, camera, center).x
            name = 'NOMBRE | Ganador' if victory else 'NOMBRE | Equipo '+team
            headers = ('TEXTO | Etiqueta victoria', 'TEXTO | Cabecera') if victory else ()
            graphics = [o for o in scene.objects if o.name == name or o.name.startswith('ESCUDO | '+team+' ') or o.name == 'ABREVIATURA | '+team or o.name in headers]
            for obj in graphics:
                if obj.name == name:
                    enable_object(obj, True)
                if obj.hide_render:
                    continue
                if obj.type == 'FONT':
                    obj.data.align_x = 'CENTER'
                    obj.data.align_y = 'CENTER'
                    if victory and obj.name == 'TEXTO | Etiqueta victoria':
                        obj.data.size = 1
                    elif victory and obj.name == 'TEXTO | Cabecera':
                        import textwrap
                        obj.data.body = '\n'.join(textwrap.fill(line, width=25, break_long_words=False, break_on_hyphens=False) for line in obj.data.body.splitlines())
                        obj.data.size = .62
                if 'rlcs_graphics_base_scale' not in obj:
                    obj['rlcs_graphics_base_scale'] = list(obj.scale)
                obj.scale = obj['rlcs_graphics_base_scale']
                if 'rlcs_graphics_base_z' not in obj:
                    obj['rlcs_graphics_base_z'] = obj.location.z
                z = 7.5 if obj.name == 'TEXTO | Etiqueta victoria' else float(obj['rlcs_graphics_base_z'])
                if victory and obj.name != 'TEXTO | Cabecera':
                    z -= .25
                if victory:
                    if obj.name == 'TEXTO | Etiqueta victoria':
                        x, z = -5.2, 5.4
                    elif obj.name == 'TEXTO | Cabecera':
                        x, z = -5.2, 4.1
                    elif obj.name == name:
                        x, z = 5.2, 2.9
                    else:
                        x, z = 5.2, 5.3
                radius = 14+.45*z/9.65
                def panel_position(x):
                    clearance = 1.25 if obj.type == 'FONT' else .9
                    return Vector((x, -8.5+math.sqrt(radius*radius-x*x)-clearance, z))
                if victory:
                    obj.location = panel_position(x)
                    target_x = world_to_camera_view(scene, camera, obj.location).x
                else:
                    lo, hi = -10.5, 10.5
                    for _ in range(32):
                        x = (lo+hi)/2
                        if world_to_camera_view(scene, camera, panel_position(x)).x < target_x:
                            lo = x
                        else:
                            hi = x
                    obj.location = panel_position((lo+hi)/2)
                obj.rotation_euler.z = math.atan2(-obj.location.x, math.sqrt(radius*radius-obj.location.x**2))
                bpy.context.view_layer.update()
                evaluated = obj.evaluated_get(depsgraph)
                projected = [world_to_camera_view(scene, camera, evaluated.matrix_world @ Vector(corner)) for corner in evaluated.bound_box]
                height = (max(p.y for p in projected)-min(p.y for p in projected))*scene.render.resolution_y
                if height > 1 and obj.name not in headers:
                    obj.scale *= (height+25)/height
                bpy.context.view_layer.update()
                if obj.type == 'FONT':
                    evaluated = obj.evaluated_get(depsgraph)
                    max_width = 6.4 if victory else 7.2
                    max_height = 1.7 if obj.name == 'TEXTO | Cabecera' else 1
                    fit = min(1, max_width/max(evaluated.dimensions.x, .001))
                    if victory:
                        fit = min(fit, max_height/max(evaluated.dimensions.z, .001))
                    obj.scale *= fit
                    bpy.context.view_layer.update()
                    evaluated = obj.evaluated_get(depsgraph)
                    projected = [world_to_camera_view(scene, camera, evaluated.matrix_world @ Vector(corner)) for corner in evaluated.bound_box]
                    left, right = ((.04, .44) if obj.name in headers else (.56, .96)) if victory else ((.04, .46) if team == 'A' else (.54, .96))
                    room = 2*max(.05, min(target_x-left, right-target_x))
                    width = max(p.x for p in projected)-min(p.x for p in projected)
                    if width > room:
                        obj.scale *= room/width
                    if not victory and obj.name == name:
                        bpy.context.view_layer.update()
                        evaluated = obj.evaluated_get(depsgraph)
                        projected = [world_to_camera_view(scene, camera, evaluated.matrix_world @ Vector(corner)) for corner in evaluated.bound_box]
                        text_height = (max(p.y for p in projected)-min(p.y for p in projected))*scene.render.resolution_y
                        if text_height > 1:
                            obj.scale *= max(1, text_height-10)/text_height
                elif victory:
                    evaluated = obj.evaluated_get(depsgraph)
                    obj.scale *= min(1, 3.8/max(evaluated.dimensions.x, .001), 3.6/max(evaluated.dimensions.z, .001))
        scene.frame_set(previous_frame)
    bpy.context.window.scene = previous_scene


def fit_victory_graphics():
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.data.scenes['02_VICTORIA_2s']
    previous_scene = bpy.context.window.scene
    previous_frame = scene.frame_current
    bpy.context.window.scene = scene
    names = ('TEXTO | Etiqueta victoria', 'TEXTO | Cabecera', 'NOMBRE | Ganador')
    objects = [o for o in scene.objects if not o.hide_render and (o.name in names or o.name.startswith('ESCUDO | Ganador'))]
    factors = {o: 1 for o in objects}
    for frame in range(scene.frame_start, scene.frame_end+1, 3):
        scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        camera = scene.camera.evaluated_get(depsgraph)
        for obj in objects:
            evaluated = obj.evaluated_get(depsgraph)
            points = [world_to_camera_view(scene, camera, evaluated.matrix_world @ Vector(corner)) for corner in evaluated.bound_box]
            lo_x, hi_x = min(p.x for p in points), max(p.x for p in points)
            lo_y, hi_y = min(p.y for p in points), max(p.y for p in points)
            center_x, center_y = (lo_x+hi_x)/2, (lo_y+hi_y)/2
            factor = min(1, (center_x-.05)/max(center_x-lo_x, .001), (.95-center_x)/max(hi_x-center_x, .001),
                         (center_y-.08)/max(center_y-lo_y, .001), (.92-center_y)/max(hi_y-center_y, .001))
            factors[obj] = min(factors[obj], max(.1, factor*.98))
    for obj, factor in factors.items():
        obj.scale *= factor
    scene.frame_set(previous_frame)
    bpy.context.window.scene = previous_scene


def raise_platforms(height=.6):
    """Raise each pedestal from its existing floor contact and carry its contents."""
    anchors = ('EQUIPO_A | ANCLA', 'EQUIPO_B | ANCLA', 'GANADOR | ANCLA')
    for obj in bpy.data.objects:
        if not (obj.name.startswith(('PLATAFORMA |', 'NOMBRE | Placa')) or obj.name in anchors):
            continue
        delta = height - float(obj.get('rlcs_platform_raise', 0))
        if abs(delta) < .00001:
            continue
        if obj.name.startswith('PLATAFORMA | Base'):
            obj.location.z += delta/2
            obj.dimensions.z += delta
        else:
            obj.location.z += delta
        obj['rlcs_platform_raise'] = height
    bpy.context.view_layer.update()


def frame_screens(scene):
    """Follow the curved screens and cut a circular recess around the pre-match VS."""
    if scene.get('rlcs_screen_frames'):
        return
    material = bpy.data.materials.get('MARCO | Acero oscuro') or bpy.data.materials.new('MARCO | Acero oscuro')
    material.use_nodes = True
    shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    shader.inputs['Base Color'].default_value = (.035, .043, .055, 1)
    shader.inputs['Metallic'].default_value = .9
    shader.inputs['Roughness'].default_value = .4
    shader.inputs['Anisotropic'].default_value = .3
    shader.inputs['Emission Strength'].default_value = 0
    nodes, links = material.node_tree.nodes, material.node_tree.links
    noise = nodes.get('MARCO | Microtextura') or nodes.new('ShaderNodeTexNoise')
    noise.name = 'MARCO | Microtextura'
    noise.inputs['Scale'].default_value = 140
    noise.inputs['Detail'].default_value = 2
    roughness = nodes.get('MARCO | Rugosidad') or nodes.new('ShaderNodeMapRange')
    roughness.name = 'MARCO | Rugosidad'
    roughness.inputs['To Min'].default_value = .32
    roughness.inputs['To Max'].default_value = .48
    links.new(noise.outputs['Fac'], roughness.inputs['Value'])
    links.new(roughness.outputs['Result'], shader.inputs['Roughness'])
    bump = nodes.get('MARCO | Relieve fino') or nodes.new('ShaderNodeBump')
    bump.name = 'MARCO | Relieve fino'
    bump.inputs['Strength'].default_value = .12
    bump.inputs['Distance'].default_value = .012
    links.new(noise.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], shader.inputs['Normal'])

    def surface(angle, z, offset=0):
        radius = 14+.45*z/9.65-offset
        angle = math.radians(angle)
        return (radius*math.sin(angle), -8.5+radius*math.cos(angle), z)

    def top(angle):
        return 8.1+1.55*(abs(angle)/54)**3

    def inner_angle(z):
        radius = 14+.45*z/9.65
        circular_x = math.sqrt(max(0, 1.14**2-(z-4.65)**2))
        return max(3, math.degrees(math.asin(circular_x/radius)))

    def outline(name, points):
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        curve.bevel_depth = .11
        curve.bevel_resolution = 1
        spline = curve.splines.new('POLY')
        spline.points.add(len(points)-1)
        for point, xyz in zip(spline.points, points):
            point.co = (*xyz, 1)
        spline.use_cyclic_u = True
        obj = bpy.data.objects.new(name, curve)
        scene.collection.objects.link(obj)
        curve.materials.append(material)

    def fit_panel(panel, vertices, faces, name):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertices, [], faces)
        mesh.materials.append(panel.data.materials[0])
        mesh.materials.append(material)
        panel.data = mesh
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        for modifier in panel.modifiers:
            if modifier.type == 'SOLIDIFY':
                modifier.material_offset = 1
                modifier.material_offset_rim = 1

    panel_limit = 53.4
    panel_bottom = .095
    top_inset = .07
    victory = scene.name.startswith('02_')
    for obj in scene.objects:
        if obj.name.startswith(('ARENA | Borde ', 'ARENA | Remate ')):
            enable_object(obj, False)
    if victory:
        panel = next(o for o in scene.objects if o.type == 'MESH' and o.name.startswith('ARENA | Victoria'))
        panel_angles = [-panel_limit+2*panel_limit*i/192 for i in range(193)]
        vertices = [surface(a, z) for a in panel_angles for z in (panel_bottom, top(a)-top_inset)]
        faces = [(2*i, 2*i+2, 2*i+3, 2*i+1) for i in range(192)]
        fit_panel(panel, vertices, faces, 'PANTALLA | Victoria encajada')
        angles = [-54+108*i/192 for i in range(193)]
        points = [surface(a, .035, .10) for a in angles]
        points += [surface(54, z, .10) for z in (.035, 9.65)]
        points += [surface(a, top(a), .10) for a in reversed(angles)]
        outline('MARCO | Victoria', points)
    else:
        vs = scene.objects.get('TEXTO | VS')
        if vs and vs.type == 'FONT':
            vs.data.align_x = 'CENTER'
            vs.data.align_y = 'CENTER'
        for side, team in ((-1, 'A'), (1, 'B')):
            panel = next(o for o in scene.objects if o.type == 'MESH' and o.name.startswith('ARENA | Equipo '+team))
            vertices, faces = [], []
            rows, columns = 160, 64
            for row in range(rows+1):
                z = panel_bottom+(top(panel_limit)-top_inset-panel_bottom)*row/rows
                top_angle = 54*((max(0, z+top_inset-8.1)/1.55)**(1/3))
                lo = max(inner_angle(z)+.35, top_angle)
                for column in range(columns+1):
                    vertices.append(surface(side*(lo+(panel_limit-lo)*column/columns), z))
            for row in range(rows):
                for column in range(columns):
                    index = row*(columns+1)+column
                    face = (index, index+1, index+columns+2, index+columns+1)
                    faces.append(tuple(reversed(face)) if side < 0 else face)
            fit_panel(panel, vertices, faces, 'PANTALLA | Recorte VS '+team)
            points = [surface(side*(54-51*i/96), .035, .10) for i in range(97)]
            points += [surface(side*inner_angle(z), z, .10) for z in [.035+(8.1-.035)*i/160 for i in range(161)]]
            points += [surface(side*a, top(a), .10) for a in [3+51*i/96 for i in range(97)]]
            points += [surface(side*54, .035, .10)]
            outline('MARCO | Equipo '+team, points)
        # Hide the animated lines inside the circular opening, behind the VS text.
        dark = bpy.data.materials.new('VS | Fondo circular')
        dark.use_nodes = True
        tree = dark.node_tree
        emission = tree.nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = (.003, .004, .006, 1)
        tree.links.new(emission.outputs[0], tree.nodes.get('Material Output').inputs['Surface'])
        def vs_surface(x, z, offset):
            radius = 14+.45*z/9.65-offset
            return (x, -8.5+math.sqrt(radius*radius-x*x), z)

        circle = [(1.14*math.cos(2*math.pi*i/128), 4.65+1.14*math.sin(2*math.pi*i/128)) for i in range(128)]
        outline('MARCO | VS', [vs_surface(x, z, .24) for x, z in circle])
        mesh = bpy.data.meshes.new('VS | Hueco circular')
        points = [vs_surface(0, 4.65, .14)]+[vs_surface(x, z, .14) for x, z in circle]
        mesh.from_pydata(points, [], [(0, i+1, (i+1)%128+1) for i in range(128)])
        mesh.materials.append(dark)
        obj = bpy.data.objects.new(mesh.name, mesh)
        scene.collection.objects.link(obj)
        if vs and vs.type == 'FONT':
            for index in range(8):
                glow = bpy.data.materials.new('VS | Resplandor blanco de letras')
                glow.use_nodes = True
                glow.node_tree.nodes.clear()
                transparent = glow.node_tree.nodes.new('ShaderNodeBsdfTransparent')
                emission = glow.node_tree.nodes.new('ShaderNodeEmission')
                emission.inputs['Color'].default_value = (1, 1, 1, 1)
                emission.inputs['Strength'].default_value = .8
                mix = glow.node_tree.nodes.new('ShaderNodeMixShader')
                mix.inputs[0].default_value = .055*(1-index/9)
                output = glow.node_tree.nodes.new('ShaderNodeOutputMaterial')
                glow.node_tree.links.new(transparent.outputs[0], mix.inputs[1])
                glow.node_tree.links.new(emission.outputs[0], mix.inputs[2])
                glow.node_tree.links.new(mix.outputs[0], output.inputs['Surface'])
                glow.surface_render_method = 'BLENDED'
                letters = vs.copy()
                letters.data = vs.data.copy()
                letters.name = 'VS | Resplandor letras'
                letters.data.offset += .012*(index+1)
                letters.location.y += .025+.003*index
                letters.data.materials.clear()
                letters.data.materials.append(glow)
                scene.collection.objects.link(letters)
    scene['rlcs_screen_frames'] = True


def animate_screen_lines(scene):
    victory = scene.name.startswith('02_')
    sections = [('Victoria', -53.4, 53.4)] if victory else [('Equipo A', -53.4, -3.35), ('Equipo B', 3.35, 53.4)]
    for section, lo, hi in sections:
        old_lines = [o for o in scene.objects if o.name.startswith('ARENA | Onda '+section)]
        if not old_lines:
            continue
        material = old_lines[0].data.materials[0]
        for obj in old_lines:
            bpy.data.objects.remove(obj, do_unlink=True)
        for index, height in enumerate((.7, 2, 3.4, 4.9, 6.3, 7.6)):
            curve = bpy.data.curves.new('ARENA | Onda '+section, 'CURVE')
            curve.dimensions = '3D'
            curve.bevel_depth = .015
            curve.bevel_resolution = 3
            spline = curve.splines.new('POLY')
            spline.points.add(96)
            for step, point in enumerate(spline.points):
                angle = lo+(hi-lo)*step/96
                z = height+.26*math.sin(math.radians(angle*3)+index*1.4)
                z = min(z, 8.1+1.55*(abs(angle)/54)**3-.4)
                radius = 14+.45*z/9.65-.065
                radians = math.radians(angle)
                point.co = (radius*math.sin(radians), -8.5+radius*math.cos(radians), z, 1)
            obj = bpy.data.objects.new(curve.name, curve)
            scene.collection.objects.link(obj)
            curve.materials.append(material)
            driver = obj.driver_add('location', 2).driver
            driver.expression = f'0.28*sin(2*pi*(frame-1)/180+{index*1.1})'


def decorate_victory(scene):
    from mathutils import Vector
    if scene.get('rlcs_victory_decoration'):
        return
    previous_scene = bpy.context.window.scene
    bpy.context.window.scene = scene
    scene.view_layers[0].update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    logo = next((o for o in scene.objects if o.name.startswith('ESCUDO | Ganador') and not o.hide_render), None)
    ring = next(o for o in scene.objects if o.name.startswith('PLATAFORMA | Aro LED'))
    color = tuple(ring.data.materials[0].diffuse_color[:3])
    sweep = bpy.data.materials.new('VICTORIA | Barrido inicial del aro')
    sweep.use_nodes = True
    tree = sweep.node_tree
    tree.nodes.clear()
    transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
    emission = tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (*(v*.65+.35 for v in color), 1)
    emission.inputs['Strength'].default_value = 18
    mix = tree.nodes.new('ShaderNodeMixShader')
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    tree.links.new(transparent.outputs[0], mix.inputs[1])
    tree.links.new(emission.outputs[0], mix.inputs[2])
    tree.links.new(mix.outputs[0], output.inputs['Surface'])
    for frame, opacity in ((1, 0), (6, 1), (32, 1), (40, 0), (scene.frame_end, 0)):
        mix.inputs[0].default_value = opacity
        mix.inputs[0].keyframe_insert(data_path='default_value', frame=frame)
    for curve in tree.animation_data.action.fcurves:
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
    sweep.surface_render_method = 'BLENDED'
    curve = bpy.data.curves.new('VICTORIA | Arco de luz', 'CURVE')
    curve.dimensions = '3D'
    curve.bevel_depth = .04
    curve.bevel_resolution = 3
    spline = curve.splines.new('POLY')
    spline.points.add(48)
    for index, point in enumerate(spline.points):
        angle = math.radians(-32+64*index/48)
        point.co = (2.23*math.cos(angle), 2.23*math.sin(angle), .065, 1)
    curve.materials.append(sweep)
    obj = bpy.data.objects.new(curve.name, curve)
    scene.collection.objects.link(obj)
    obj.location = ring.evaluated_get(depsgraph).matrix_world.translation
    for frame, angle in ((1, -math.pi/2), (37, 3*math.pi/2)):
        obj.rotation_euler.z = angle
        obj.keyframe_insert(data_path='rotation_euler', frame=frame)
    for curve in obj.animation_data.action.fcurves:
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
    scene['rlcs_victory_decoration'] = True
    bpy.context.window.scene = previous_scene


def style_arena():
    from mathutils import Vector
    floor = bpy.data.materials.get('ARENA | Suelo satinado')
    if floor and floor.use_nodes:
        shader = next(n for n in floor.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value = (.014, .018, .025, 1)
        shader.inputs['Metallic'].default_value = .2
        shader.inputs['Roughness'].default_value = .42
    for obj in bpy.data.objects:
        if obj.name.startswith(('NOMBRE | Placa', 'Foco visible')):
            enable_object(obj, False)
    for scene in bpy.data.scenes:
        frame_screens(scene)
        if scene.world and scene.world.use_nodes:
            for node in scene.world.node_tree.nodes:
                if node.type == 'BACKGROUND':
                    node.inputs['Strength'].default_value = .022
        animate_screen_lines(scene)
        for obj in list(scene.objects):
            if obj.type != 'LIGHT':
                continue
            if obj.name.startswith(('ARENA | Luz blanca coche', 'ARENA | Foco cenital', 'ARENA | Luz aro')):
                bpy.data.objects.remove(obj, do_unlink=True)
                continue
            light = obj.data
            if obj.get('rlcs_headlight') or light.type == 'SPOT':
                light.specular_factor = .15
            else:
                if 'rlcs_original_energy' not in light:
                    light['rlcs_original_energy'] = light.energy
                light.energy = light['rlcs_original_energy']*.22
                light.specular_factor = .35
        victory = scene.name.startswith('02_')
        mounts = ((-.95, -1.1), (.95, -1.1)) if victory else ((-4.3, -.6), (4.3, -.6))
        for index, (x, y) in enumerate(mounts):
            light = bpy.data.lights.new('ARENA | Foco cenital', 'AREA')
            light.energy = 1200 if victory else 1600
            light.color = (1, .97, .92)
            light.shape = 'DISK'
            light.size = 3
            light.specular_factor = .65
            obj = bpy.data.objects.new(light.name, light)
            scene.collection.objects.link(obj)
            obj.location = (x, y-.4, 7.5)
            target = Vector((0 if victory else x, y, 1.2))
            obj.rotation_euler = (target-obj.location).to_track_quat('-Z', 'Y').to_euler()
        rings = [o for o in scene.objects if o.name.startswith('PLATAFORMA | Aro LED')]
        for ring in rings:
            source = ring.data.materials[0]
            material = source if source.get('rlcs_emissive_ring') else source.copy()
            material.name = 'ARO | ' + ring.name
            material['rlcs_emissive_ring'] = True
            material.use_nodes = True
            shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            color = tuple(material.diffuse_color[:3])
            shader.inputs['Emission Color'].default_value = (*color, 1)
            shader.inputs['Emission Strength'].default_value = 7
            nodes = material.node_tree.nodes
            emission = nodes.get('ARO | Emision continua') or nodes.new('ShaderNodeEmission')
            emission.name = 'ARO | Emision continua'
            emission.inputs['Color'].default_value = (*color, 1)
            emission.inputs['Strength'].default_value = 7
            output = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL')
            material.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
            ring.data.materials[0] = material
            for index in range(RING_LIGHT_COUNT):
                angle = 2*math.pi*index/RING_LIGHT_COUNT
                light = bpy.data.lights.new('ARENA | Luz aro', 'POINT')
                light.color = color
                light.energy = 112/RING_LIGHT_COUNT
                light.shadow_soft_size = .65
                light.specular_factor = .25
                obj = bpy.data.objects.new(light.name, light)
                scene.collection.objects.link(obj)
                obj.location = ring.matrix_world.translation + Vector((2.22*math.cos(angle), 2.22*math.sin(angle), .04))
        if victory:
            decorate_victory(scene)


def configure(config, folder):
    remove_legacy_elements()
    raise_platforms()
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
        environment_color = config.get('background_color', settings['color']) if config.get('animation_mode') == 'showcase' else settings['color']
        color_material(bpy.data.materials['TEAM_' + team + ' | Color editable'], rgb(environment_color))
        for arena_material in bpy.data.materials:
            if arena_material.get('arena_team') == team:
                gain = arena_material.get('arena_gain', 1)
                color_material(arena_material, tuple(v*gain for v in rgb(environment_color)))
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
    set_text(['TEXTO | Etiqueta victoria'], 'GANADOR')
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
                enable_object(obj, bool(settings.get('logo')) and bool(node))
    pattern = bpy.data.materials.get('SCREEN | Patron victoria')
    if pattern:
        color_material(pattern, tuple(v * .24 for v in rgb(config.get('background_color', settings['color']) if config.get('animation_mode') == 'showcase' else settings['color'])))
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
    align_team_graphics()
    fit_victory_graphics()
    style_arena()
    if not config.get('video'):
        bpy.ops.file.pack_all()


def showcase_camera(scene):
    """Six slow camera moves with deliberate cuts, using the victory arena."""
    from mathutils import Vector
    bpy.context.window.scene = scene
    scene.frame_set(1)
    anchor = bpy.data.objects['GANADOR | ANCLA']
    matrix = anchor.matrix_world.copy()
    anchor.animation_data_clear()
    anchor.matrix_world = matrix
    scene.view_layers[0].update()
    car_parts = [o for o in scene.objects if o.type == 'MESH' and not o.hide_render
                 and o in anchor.children_recursive]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = [o.evaluated_get(depsgraph).matrix_world @ Vector(corner)
              for o in car_parts for corner in o.bound_box]
    if not points:
        raise ValueError('No se encuentra el coche de la presentación.')
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low+high)/2
    width = max(high.x-low.x, 1)
    length = max(high.y-low.y, 1)
    size = max(width, length)
    scene.frame_start, scene.frame_end = 1, 600
    scene.render.fps = 30
    scene.render.fps_base = 1
    scene.timeline_markers.clear()
    label = bpy.data.objects.get('TEXTO | Etiqueta victoria')
    if label:
        label.hide_render = True
    import textwrap
    header = bpy.data.objects.get('TEXTO | Cabecera')
    logo = next((o for o in scene.objects if o.name.startswith('ESCUDO | Ganador') and not o.hide_render), None)
    has_text = bool(header and header.data.body.strip())
    for graphic in scene.objects:
        if graphic.type == 'FONT' and graphic != header:
            graphic.hide_render = True
        if not graphic.hide_render and (graphic == header or graphic == logo):
            if graphic == header:
                graphic.data.body = textwrap.fill(' '.join(graphic.data.body.split()), width=26, break_long_words=False, break_on_hyphens=False)
                graphic.data.size = 1.0
                graphic.scale = (1, 1, 1)
                x, z = (-3.0 if logo else 0), 4.8
                radius = 14+.45*z/9.65
                graphic.location = (x, -8.5+math.sqrt(radius*radius-x*x)-1.25, z)
                graphic.rotation_euler.z = math.atan2(-x, math.sqrt(radius*radius-x*x))
                scene.view_layers[0].update()
                factor = min(1, 6.5/max(graphic.dimensions.x, .001), 2.2/max(graphic.dimensions.z, .001))
                graphic.scale *= factor
            else:
                x = graphic.location.x*.6 if has_text else 0
                z = 4.1
                radius = 14+.45*z/9.65
                graphic.location = (x, -8.5+math.sqrt(radius*radius-x*x)-.9, z)
                graphic.rotation_euler.z = math.atan2(-x, math.sqrt(radius*radius-x*x))
                scene.view_layers[0].update()
                graphic.scale *= min(.8, 2.2/max(graphic.dimensions.z, .001), 3/max(graphic.dimensions.x, .001))
            for frame, hidden in ((1, True), (510, True), (511, False)):
                graphic.hide_render = hidden
                graphic.keyframe_insert(data_path='hide_render', frame=frame)
    if label:
        label.animation_data_clear()
        label.hide_render = True
    # Offsets are relative to the actual car bounds, keeping all three models framed.
    shots = [
        ('Frontal tres cuartos', 1, 120, (-1.55, -2.15, 1.05), (-1.25, -1.85, .75), (0, 0, 0), 48),
        ('Frontal y faros', 121, 210, (.35, -1.85, .18), (-.35, -1.65, .24), (0, -.22, -.04), 55),
        ('Rueda y lateral', 211, 300, (-1.35, -.9, .05), (-1.5, -.25, .12), (-.22, -.12, -.08), 58),
        ('Perfil', 301, 420, (-2.15, .25, .45), (-1.85, .8, .6), (0, 0, 0), 50),
        ('Trasera tres cuartos', 421, 510, (-.65, .95, .35), (-.35, 1.05, .4), (0, .12, 0), 32),
        ('Plano de cierre', 511, 600, (.95, -2.5, 1.2), (.4, -4, 1.4), (0, 0, .15), 40),
    ]
    for title, start, end, begin, finish, aim, lens in shots:
        camera_data = bpy.data.cameras.new('PRESENTACIÓN | '+title)
        camera_data.lens = lens
        camera_data.clip_start = .03
        camera_data.clip_end = 250
        camera = bpy.data.objects.new(camera_data.name, camera_data)
        scene.collection.objects.link(camera)
        target = center+Vector(aim)*size
        for frame, offset in ((start, begin), (end, finish)):
            camera.location = center+Vector(offset)*size
            camera.rotation_euler = (target-camera.location).to_track_quat('-Z', 'Y').to_euler()
            camera.keyframe_insert(data_path='location', frame=frame)
            camera.keyframe_insert(data_path='rotation_euler', frame=frame)
        for curve in camera.animation_data.action.fcurves:
            for key in curve.keyframe_points:
                key.interpolation = 'BEZIER'
                key.handle_left_type = key.handle_right_type = 'AUTO_CLAMPED'
        marker = scene.timeline_markers.new(title, frame=start)
        marker.camera = camera
        if start == 1:
            scene.camera = camera
    scene.frame_set(1)


def main(job):
    config = json.loads(Path(job).read_text(encoding='utf-8'))
    folder = Path(config['output'])
    folder.mkdir(parents=True, exist_ok=True)
    engine = config.get('engine', 'EEVEE')
    if engine not in ('EEVEE', 'CYCLES'):
        raise ValueError('Motor de render no compatible: '+str(engine))
    video = bool(config.get('video'))
    canonical = 'render_clips' in config
    if video:
        requested = config.get('render_clips')
        if requested is None:
            requested = []
            allowed = config.get('only_scenes', ['Prepartido', 'Victoria'])
            if 'Prepartido' in allowed and not config.get('only_victory') and 'Prepartido' not in config.get('cached_videos', []):
                requested.append('Prepartido')
            if 'Victoria' in allowed and 'Victoria' not in config.get('cached_videos', []):
                requested.append('Victoria_'+config['winner'])
        valid = {'Prepartido', 'Victoria_A', 'Victoria_B', 'Pausa'}
        if any(name not in valid for name in requested):
            raise ValueError('Vídeo solicitado no válido.')
        winners = list(dict.fromkeys(('A' if name == 'Pausa' else config['winner'] if name == 'Prepartido' else name[-1]) for name in requested))
    else:
        requested = ['Prepartido', 'Victoria_'+config['winner']]
        if config.get('animation_mode') == 'showcase':
            requested = ['Pausa']
            winners = ['A']
        else:
            winners = [config['winner']]
    completed = []
    for winner in winners:
        bpy.ops.wm.open_mainfile(filepath=config['template'])
        bpy.context.preferences.filepaths.save_version = 0
        current = dict(config, winner=winner)
        configure(current, folder)
        for scene in bpy.data.scenes:
            scene.render.engine = 'BLENDER_EEVEE_NEXT' if engine == 'EEVEE' else 'CYCLES'
            if engine == 'EEVEE':
                scene.eevee.taa_render_samples = config.get('samples', 32)
                scene.eevee.use_raytracing = False
            scene.cycles.samples = config.get('samples', 24 if video else 16)
        bpy.data.orphans_purge(do_recursive=True)
        scenes = [('Prepartido', '01_PREPARTIDO_13s', 300), ('Victoria_'+winner, '02_VICTORIA_2s', 1)]
        scenes.append(('Pausa', '02_VICTORIA_2s', 570))
        for name, scene_name, frame in scenes:
            if name not in requested or name in completed:
                continue
            scene = bpy.data.scenes[scene_name]
            bpy.context.window.scene = scene
            showcase = name == 'Pausa'
            if showcase:
                showcase_camera(scene)
            if video:
                basename = name if canonical or name == 'Prepartido' or showcase else 'Victoria'
                scene.render.resolution_percentage = config.get('resolution', 100)
                scene.render.image_settings.file_format = 'FFMPEG'
                scene.render.ffmpeg.format = 'MPEG4'
                scene.render.ffmpeg.codec = 'H264'
                scene.render.ffmpeg.constant_rate_factor = 'HIGH'
                pending = folder/(basename+'.en_proceso.mp4')
                scene.render.filepath = str(pending)
                if config.get('test_frames'):
                    scene.frame_end = scene.frame_start+config['test_frames']-1
                announce('Exportando '+basename+' · '+engine)
                bpy.ops.render.render(animation=True)
                from media import mp4_duration
                expected = (scene.frame_end-scene.frame_start+1)*scene.render.fps_base/scene.render.fps
                if abs(mp4_duration(pending)-expected) > .05:
                    raise RuntimeError('Vídeo incompleto: '+basename)
                pending.replace(folder/(basename+'.mp4'))
            else:
                basename = 'Pausa' if showcase else ('Prepartido' if name == 'Prepartido' else 'Victoria')
                if config.get('only_victory') and basename == 'Prepartido':
                    continue
                if config.get('only_scenes') and basename not in config['only_scenes']:
                    continue
                scene.frame_set(frame)
                scene.render.resolution_percentage = config.get('preview_resolution', 50)
                scene.render.image_settings.file_format = 'PNG'
                scene.render.filepath = str(folder/(basename+'.png'))
                announce('Generando vista previa: '+basename+' · '+engine)
                bpy.ops.render.render(write_still=True)
            completed.append(name)
    (folder/'completado.json').write_text(json.dumps(dict(video=video, clips=completed)), encoding='utf-8')
    announce('Listo. Archivos guardados en '+str(folder))


if __name__ == '__main__':
    try:
        main(sys.argv[sys.argv.index('--') + 1])
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

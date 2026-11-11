"""Blender paint approximations; custom decals are deliberately excluded."""
import colorsys

FINISHES = ('Brillante', 'Anodizada', 'Mate', 'Metálico (suave)', 'Perla anodizada')
PARAMETERS = {
    'Brillante': (.12, .18, .65, .12, .0),
    'Anodizada': (.85, .22, .35, .15, .25),
    'Mate': (.0, .82, .0, .3, .0),
    'Metálico (suave)': (.65, .34, .22, .24, .12),
    'Perla anodizada': (.78, .19, .65, .12, .2),
}


def apply_finish(material, finish, custom_skin=False):
    if custom_skin:
        return
    if finish not in PARAMETERS:
        raise ValueError('Acabado de pintura no válido: ' + str(finish))
    shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    values = dict(zip(('Metallic', 'Roughness', 'Coat Weight', 'Coat Roughness', 'Anisotropic'), PARAMETERS[finish]))
    values.update({'Thin Film Thickness': 0, 'Thin Film IOR': 1.35})
    for name, value in values.items():
        socket = shader.inputs[name]
        for link in list(socket.links):
            material.node_tree.links.remove(link)
        socket.default_value = value
    if finish == 'Perla anodizada':
        # Angular pearl tint also works in EEVEE, where thin film differs from Cycles.
        base = tuple(shader.inputs['Base Color'].default_value)
        hue, saturation, brightness = colorsys.rgb_to_hsv(*base[:3])
        pearl = colorsys.hsv_to_rgb((hue+.10) % 1, saturation*.75, brightness)
        weight = material.node_tree.nodes.new('ShaderNodeLayerWeight')
        weight.inputs['Blend'].default_value = .35
        ramp = material.node_tree.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = base
        ramp.color_ramp.elements[1].color = (*pearl, 1)
        material.node_tree.links.new(weight.outputs['Facing'], ramp.inputs['Fac'])
        material.node_tree.links.new(ramp.outputs['Color'], shader.inputs['Base Color'])
        shader.inputs['Thin Film Thickness'].default_value = 380
    material['rlcs_paint_finish'] = finish

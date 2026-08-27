import os
import shutil
import bpy

from pxr import UsdGeom, UsdShade, Sdf, Gf, Usd
from publisher.exporter.common import looks_scope_path, material_prim_name, sanitize_name
from publisher.monke_logging import get_logger


logger = get_logger(__name__)
COLOR_INPUTS = {
    "diffuseColor": ("Base Color",),
}
SCALAR_INPUTS = {
    "metallic": ("Metallic",),
    "roughness": ("Roughness",),
    "ior": ("IOR",),
    "opacity": ("Alpha",),
    "clearcoat": ("Coat Weight", "Clearcoat"),
    "clearcoatRoughness": ("Coat Roughness", "Clearcoat Roughness"),
}
EMISSION_COLOR_NAMES = ("Emission Color", "Emission")
EMISSION_STRENGTH_NAMES = ("Emission Strength",)


class MaterialsLayerExporter:
    """
    collect asset materials under a Look prim using UsdPreviewSurface shaders.
    Currently supports basic Principled BSDF inputs (textures and scalar values).
    Advanced material networks are not yet supported.
    """

    def __init__(self, textures_dir, meter_per_unit):
        self.textures_dir = textures_dir
        self.meter_per_unit = meter_per_unit
        os.makedirs(self.textures_dir, exist_ok=True)

    def export(self, output_path, asset_item):
        logger.debug("Exporting materials...")
        stage = Usd.Stage.CreateNew(output_path)
        UsdGeom.SetStageMetersPerUnit(stage, self.meter_per_unit)
        looks_path = looks_scope_path(asset_item.name, bool(asset_item.armature_objects))
        UsdGeom.Scope.Define(stage, looks_path)

        for material in asset_item.materials.values():
            self._write_material(stage, f"{looks_path}/{material_prim_name(material.name)}", material)

        for variants in asset_item.material_variants.values():
            for material in variants.values():
                self._write_material(stage, f"{looks_path}/{material_prim_name(material.name)}", material)
        return stage
    
    def _write_material(self, stage, material_path, material):
        usd_material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")

        bsdf = self._find_principled_bsdf(material)
        if bsdf is None:
            # no principled BSDF to read from, fall back to a flat magenta
            shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1.0, 0.0, 0.7))
        else:
            for usd_input, names in COLOR_INPUTS.items():
                socket = self._first_socket(bsdf, names)
                if socket:
                    self._write_color_input(stage, material_path, shader, socket, usd_input)

            for usd_input, names in SCALAR_INPUTS.items():
                socket = self._first_socket(bsdf, names)
                if socket:
                    self._write_scalar_input(stage, material_path, shader, socket, usd_input)

            self._write_emission(stage, material_path, shader, bsdf)
            self._write_normal(stage, material_path, shader, bsdf)

        usd_material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    def _write_color_input(self, stage, material_path, shader, socket, usd_input):
        tex_image = self._resolve_texture(socket)
        if tex_image:
            self._connect_texture(stage, material_path, shader, usd_input, tex_image, Sdf.ValueTypeNames.Color3f, "rgb")
            return
        value = socket.default_value
        shader.CreateInput(usd_input, Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(value[0], value[1], value[2]))

    def _write_scalar_input(self, stage, material_path, shader, socket, usd_input):
        tex_image = self._resolve_texture(socket)
        if tex_image:
            self._connect_texture(stage, material_path, shader, usd_input, tex_image, Sdf.ValueTypeNames.Float, "r")
            return
        shader.CreateInput(usd_input, Sdf.ValueTypeNames.Float).Set(float(socket.default_value))

    def _write_emission(self, stage, material_path, shader, bsdf):
        color_socket = self._first_socket(bsdf, EMISSION_COLOR_NAMES)
        if color_socket is None:
            return

        tex_image = self._resolve_texture(color_socket)
        if tex_image:
            self._connect_texture(stage, material_path, shader, "emissiveColor", tex_image, Sdf.ValueTypeNames.Color3f, "rgb")
            return

        strength_socket = self._first_socket(bsdf, EMISSION_STRENGTH_NAMES)
        strength = float(strength_socket.default_value) if strength_socket else 1.0
        color = color_socket.default_value
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(color[0] * strength, color[1] * strength, color[2] * strength)
        )

    def _write_normal(self, stage, material_path, shader, bsdf):
        normal_socket = bsdf.inputs.get("Normal")
        if normal_socket is None or not normal_socket.is_linked:
            return

        node = normal_socket.links[0].from_node
        if node.type == "NORMAL_MAP":
            color_input = node.inputs.get("Color")
            tex_image = self._resolve_texture(color_input) if color_input else None
        elif node.type == "TEX_IMAGE":
            tex_image = node.image
        else:
            tex_image = None

        if not tex_image:
            return

        self._connect_texture(
            stage, material_path, shader, "normal", tex_image, Sdf.ValueTypeNames.Normal3f, "rgb", scale_bias=True
        )

    @staticmethod
    def _find_principled_bsdf(material):
        if not material.use_nodes or not material.node_tree:
            return None
        for node in material.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                return node
        return None

    @staticmethod
    def _first_socket(bsdf, names):
        for name in names:
            socket = bsdf.inputs.get(name)
            if socket is not None:
                return socket
        return None

    @staticmethod
    def _resolve_texture(socket):
        """the Image Texture node feeding `socket`, if any (and it has a file on disk)"""
        if socket is None or not socket.is_linked:
            return None
        node = socket.links[0].from_node
        if node.type == "TEX_IMAGE" and node.image and node.image.filepath:
            return node.image
        return None

    def _connect_texture(self, stage, material_path, shader, usd_input, image, value_type, output_channel, scale_bias=False):
        texture_asset_path = self._copy_texture(image)

        texture_shader = UsdShade.Shader.Define(stage, f"{material_path}/{sanitize_name(image.name)}_Texture")
        texture_shader.CreateIdAttr("UsdUVTexture")
        texture_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_asset_path)

        uv_reader = self._get_uv_reader(stage, material_path)
        texture_shader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(uv_reader.ConnectableAPI(), "result")

        if image.colorspace_settings.name == "Non-Color":
            texture_shader.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("raw")

        if scale_bias:
            texture_shader.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2, 2, 2, 1))
            texture_shader.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1, -1, -1, 0))

        if output_channel == "rgb":
            texture_output = texture_shader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        else:
            texture_output = texture_shader.CreateOutput(output_channel, Sdf.ValueTypeNames.Float)

        shader.CreateInput(usd_input, value_type).ConnectToSource(texture_output)

    def _copy_texture(self, image):
        source_path = bpy.path.abspath(image.filepath)
        basename = os.path.basename(source_path)
        shutil.copy2(source_path, os.path.join(self.textures_dir, basename))
        return os.path.join("../textures", basename)

    @staticmethod
    def _get_uv_reader(stage, material_path):
        reader = UsdShade.Shader.Define(stage, f"{material_path}/uvReader_st")
        reader.CreateIdAttr("UsdPrimvarReader_float2")
        reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)
        return reader

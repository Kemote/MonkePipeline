import os
import bpy
import shutil

from pxr import UsdGeom, UsdShade, Sdf, Gf
from publisher.exporter.common import looks_scope_path, material_prim_name


class MaterialsLayerExporter:
    # TODO: now its takes only bae color from BSDF, we need to get more data from materials,
    # maybe it should be converted to MaterialX

    """
    collects every material used by the asset's meshes under /{asset_name}/Looks -
    including each variant material ("base_VAR_variant"), written as an ordinary
    Material prim named "{base}_{variant}". switching between variant materials is
    done by the binding variantSets authored in the material binding layer, not here
    """
    def __init__(self, textures_dir):
        self.textures_dir = textures_dir
        os.makedirs(self.textures_dir)

    def export(self, stage, asset_item):
        looks_path = looks_scope_path(asset_item.name)
        UsdGeom.Scope.Define(stage, looks_path)

        for material in asset_item.materials.values():
            self._write_material(stage, f"{looks_path}/{material_prim_name(material.name)}", material)

        for variants in asset_item.material_variants.values():
            for material in variants.values():
                self._write_material(stage, f"{looks_path}/{material_prim_name(material.name)}", material)

    def _write_material(self, stage, material_path, material):
        usd_material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")

        base_color =  self._get_base_color(material)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(base_color[0], base_color[1], base_color[2])
        )

        texture_path = self._find_base_color_texture(material)
        if texture_path:
            # copy texture file
            basename = os.path.basename(texture_path)
            texture_dst = os.path.join(self.textures_dir, basename)
            shutil.copy2(texture_path, texture_dst)
            # set texture connection
            self._connect_texture(stage, material_path, shader, os.path.join("../textures", basename))

        usd_material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    @staticmethod
    def _get_base_color(material):
        rgba = [1.0, 0.0, 0.7]
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    rgba = list(node.inputs[0].default_value)
        return rgba

    @staticmethod
    def _find_base_color_texture(material):
        if not material.use_nodes or not material.node_tree:
            return None
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                return bpy.path.abspath(node.image.filepath)
        return None

    def _connect_texture(self, stage, material_path, shader, texture_path):
        texture_shader = UsdShade.Shader.Define(stage, f"{material_path}/BaseColorTexture")
        texture_shader.CreateIdAttr("UsdUVTexture")
        texture_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_path)
        texture_output = texture_shader.CreateOutput("rgb", Sdf.ValueTypeNames.Color3f)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(texture_output)

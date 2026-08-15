import os

from pxr import Usd, UsdGeom
from publisher.exporter.armature import ArmatureLayerExporter
from publisher.exporter.common import FPS, sanitize_name
from publisher.exporter.materials import MaterialsLayerExporter
from publisher.exporter.mesh import MeshLayerExporter
from templates.templates import Templates


class UsdExporter:
    def __init__(self, settings):
        self.up_axis = {
            "y": UsdGeom.Tokens.y,
            "z": UsdGeom.Tokens.z
        }[settings["up_axis"]]
                
        self.extension = settings["extension"]
        self.meter_per_unit = settings["meter_per_unit"]
        self.export_geom = settings["export_geometry"]
        self.export_mat = settings["export_materials"]
        self.export_armature = settings["export_armature"]

    def export(self, asset_item):
        asset_name = asset_item.name

        # output_dir = os.path.join(self.output_dir, asset_name)
        # layers_dir = os.path.join(output_dir, "layers")
        # textures_dir = os.path.join(output_dir, "textures")
        # os.makedirs(layers_dir, exist_ok=True)

        templates = Templates()
        fields = {
            "ext": self.extension,
            "project_name": str(os.environ.get("PROJECTNAME")),
            "name": asset_name
        }
        main_file_template = templates.get_template_by_name("asset_main_file")
        sublayer_file_template = templates.get_template_by_name("asset_sublayer_file")
        mesh_variants_template = templates.get_template_by_name("asset_mesh_variants_output")
        textures_template = templates.get_template_by_name("asset_textures_output")

        main_file_path = templates.resolve_template(main_file_template, fields)
        fields["step"] = "geom"
        geom_file_path = templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "look"
        look_file_path = templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "rig"
        rig_file_path = templates.get_new_file_path(sublayer_file_template, fields)
        mesh_variants_output = templates.get_new_file_path(mesh_variants_template, fields)
        textures_output = templates.get_new_file_path(textures_template, fields)
        layer_paths = []

        if self.export_geom:
            variant_base_fields = {
                "ext": fields["ext"],
                "project_name": fields["project_name"],
                "name": fields["name"],
            }
            mesh_exporter = MeshLayerExporter(templates, variant_base_fields, mesh_variants_output, self.extension)
            self._write_layer(geom_file_path, mesh_exporter, asset_item)
            layer_paths.append(geom_file_path)

        if self.export_mat:
            materials_exporter = MaterialsLayerExporter(textures_output)
            self._write_layer(look_file_path, materials_exporter, asset_item)
            layer_paths.append(look_file_path)

        if self.export_armature:
            armature_exporter = ArmatureLayerExporter()
            self._write_layer(rig_file_path, armature_exporter, asset_item)
            layer_paths.append(rig_file_path)

        main_stage = Usd.Stage.CreateNew(main_file_path)
        self._set_fps(main_stage)
        self._set_metadata(main_stage)
        UsdGeom.SetStageUpAxis(main_stage, self.up_axis)
        UsdGeom.SetStageMetersPerUnit(main_stage, self.meter_per_unit)

        main_layer = main_stage.GetRootLayer()
        for layer_path in layer_paths:
            main_layer.subLayerPaths.append(os.path.relpath(layer_path, os.path.dirname(main_file_path)))

        main_layer.defaultPrim = sanitize_name(asset_name)
        main_layer.Save()
        return main_file_path

    def _write_layer(self, file_path, layer_exporter, asset_item):
        stage = Usd.Stage.CreateNew(file_path)
        layer_exporter.export(stage, asset_item)
        self._set_fps(stage)
        stage.GetRootLayer().Save()
                
    @staticmethod
    def _set_fps(stage):
        stage.SetFramesPerSecond(FPS)
        stage.SetTimeCodesPerSecond(FPS)

    @staticmethod
    def _set_metadata(stage):
        root_layer = stage.GetRootLayer()
        layer_data = root_layer.customLayerData
        layer_data["userName"] = os.environ.get("MONKENAME", "unknown")
        root_layer.customLayerData = layer_data

import os

from pxr import Usd, UsdGeom, Kind
from publisher.exporter.armature import ArmatureLayerExporter
from publisher.exporter.common import FPS, sanitize_name
from publisher.exporter.materials import MaterialsLayerExporter
from publisher.exporter.mesh import MeshLayerExporter
from templates.templates import Templates
from publisher.monke_logging import get_logger


logger = get_logger(__name__)


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
        fields = {
            "ext": self.extension,
            "project_name": str(os.environ.get("PROJECTNAME")),
            "name": asset_name
        }
        templates = Templates()
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
        layer_paths_dict = {
            "geom": None,
            "look": None,
            "rig": None,
        }

        if self.export_geom:
            variant_base_fields = {
                "ext": fields["ext"],
                "project_name": fields["project_name"],
                "name": fields["name"],
            }
            mesh_exporter = MeshLayerExporter(variant_base_fields, mesh_variants_output)
            self._write_layer(geom_file_path, mesh_exporter, asset_item)
            layer_paths_dict["geom"] = geom_file_path

        if self.export_mat:
            materials_exporter = MaterialsLayerExporter(textures_output)
            self._write_layer(look_file_path, materials_exporter, asset_item)
            layer_paths_dict["look"] = look_file_path

        if self.export_armature:
            armature_exporter = ArmatureLayerExporter()
            self._write_layer(rig_file_path, armature_exporter, asset_item)
            layer_paths_dict["rig"] = rig_file_path

        # creating main stage
        if os.path.exists(main_file_path):
            main_stage = Usd.Stage.Open(main_file_path)
        else:
            main_stage = Usd.Stage.CreateNew(main_file_path)

        # stage settings
        self._set_fps(main_stage)
        self._set_metadata(main_stage)
        UsdGeom.SetStageUpAxis(main_stage, self.up_axis)
        UsdGeom.SetStageMetersPerUnit(main_stage, self.meter_per_unit)        

        # add main prim
        main_prim = main_stage.OverridePrim(f"/{sanitize_name(asset_name)}")
        main_prim.SetKind(Kind.Tokens.component)
        main_stage.SetDefaultPrim(main_prim)

        # setting sublayers, strongest first
        root_layer = main_stage.GetRootLayer()
        current_sublayers = list(root_layer.subLayerPaths)
        step_order = ("geom", "look", "rig")

        new_monke_paths = {
            step: templates.convert_path_to_monkedDisc(sublayer_file_template, layer_paths_dict[step])
            for step in step_order
            if layer_paths_dict[step]
        }

        final_sublayers = []
        for step in step_order:
            if step in new_monke_paths:
                final_sublayers.append(new_monke_paths[step])
                continue
            existing = next((path for path in current_sublayers if f"_{step}_" in path), None)            
            if existing:
                final_sublayers.append(existing)

        root_layer.subLayerPaths = final_sublayers
        root_layer.Save()

        return main_file_path

    def _write_layer(self, file_path, layer_exporter, asset_item):
        logger.debug(f"Write layer: {file_path} for asset: {asset_item.name }")
        stage = layer_exporter.export(file_path, asset_item)
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

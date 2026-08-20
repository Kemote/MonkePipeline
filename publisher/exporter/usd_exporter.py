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
        self.templates = Templates()     
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
        main_file_template = self.templates.get_template_by_name("asset_main_file")
        sublayer_file_template = self.templates.get_template_by_name("asset_sublayer_file")
        mesh_variants_template = self.templates.get_template_by_name("asset_mesh_variants_output")
        textures_template = self.templates.get_template_by_name("asset_textures_output")

        main_file_path = self.templates.resolve_template(main_file_template, fields)
        fields["step"] = "geom"
        geom_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "look"
        look_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "rig"
        rig_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        mesh_variants_output = self.templates.get_new_file_path(mesh_variants_template, fields)
        textures_output = self.templates.get_new_file_path(textures_template, fields)
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
            mesh_exporter = MeshLayerExporter(self.templates, variant_base_fields, mesh_variants_output, self.extension)
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
        print("main stage: " + main_file_path)
        if os.path.exists(main_file_path):
            main_stage = Usd.Stage.Open(main_file_path)
        else:
            main_stage = Usd.Stage.CreateNew(main_file_path)

        # stage settings
        self._set_fps(main_stage)
        self._set_metadata(main_stage)
        UsdGeom.SetStageUpAxis(main_stage, self.up_axis)
        UsdGeom.SetStageMetersPerUnit(main_stage, self.meter_per_unit)

        # setting sublayers, strongest first
        root_layer = main_stage.GetRootLayer()
        current_sublayers = list(root_layer.subLayerPaths)
        print("SUBLAYERSL: %s" % current_sublayers)
        step_order = ("geom", "look", "rig")
        new_monke_paths = {
            step: self.templates.convert_path_to_monkedDisc(sublayer_file_template, layer_paths_dict[step])
            for step in step_order
            if layer_paths_dict[step]
        }

        final_sublayers = []
        for step in step_order:
            if step in new_monke_paths:
                final_sublayers.append(new_monke_paths[step])
                continue
            existing = next((path for path in current_sublayers if f"_{step}_" in path), None)
            print(f"FIELDS: {fields}")
            print(f"existing: {existing}")
            
            if existing:
                final_sublayers.append(existing)

        root_layer.subLayerPaths = final_sublayers
        root_layer.Save()

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

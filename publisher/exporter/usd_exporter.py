import os

from pxr import Usd, UsdGeom
from publisher.exporter.armature import ArmatureLayerExporter
from publisher.exporter.common import FPS, sanitize_name
from publisher.exporter.materials import MaterialsLayerExporter
from publisher.exporter.mesh import MeshLayerExporter


class UsdExporter:
    def __init__(self, settings):
        self.up_axis = {
            "y": UsdGeom.Tokens.y,
            "z": UsdGeom.Tokens.z
        }[settings["up_axis"]]
                
        self.output_dir = settings["filepath"]
        self.extension = settings["extension"]
        self.meter_per_unit = settings["meter_per_unit"]
        self.export_geom = settings["export_geometry"]
        self.export_mat = settings["export_materials"]
        self.export_armature = settings["export_armature"]
        
        self.materials_exporter = MaterialsLayerExporter()
        self.armature_exporter = ArmatureLayerExporter()

    def export(self, asset_item):
        asset_name = asset_item.name
        output_dir = os.path.join(self.output_dir, asset_name)
        layers_dir = os.path.join(output_dir, "layers")
        os.makedirs(layers_dir, exist_ok=True)

        layer_paths = []

        if self.export_mat:
            materials_path = os.path.join(layers_dir, f"{asset_name}_materials.{self.extension}")
            self._write_layer(materials_path, self.materials_exporter, asset_item)
            layer_paths.append(materials_path)

        if self.export_geom:
            mesh_exporter = MeshLayerExporter(output_dir, self.extension)
            geom_path = os.path.join(layers_dir, f"{asset_name}_geo.{self.extension}")
            self._write_layer(geom_path, mesh_exporter, asset_item)
            layer_paths.append(geom_path)

        if self.export_armature:
            armature_path = os.path.join(layers_dir, f"{asset_name}_armature.{self.extension}")
            self._write_layer(armature_path, self.armature_exporter, asset_item)
            layer_paths.append(armature_path)

        main_path = os.path.join(output_dir, f"{asset_name}.{self.extension}")
        main_stage = Usd.Stage.CreateNew(main_path)
        self._set_fps(main_stage)
        self._set_metadata(main_stage)
        UsdGeom.SetStageUpAxis(main_stage, self.up_axis)
        UsdGeom.SetStageMetersPerUnit(main_stage, self.meter_per_unit)

        main_layer = main_stage.GetRootLayer()
        # TODO: add check for existing versions if None
        for layer_path in layer_paths:
            main_layer.subLayerPaths.append(os.path.relpath(layer_path, output_dir))
        main_layer.defaultPrim = sanitize_name(asset_name)
        main_layer.Save()
        return main_path

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

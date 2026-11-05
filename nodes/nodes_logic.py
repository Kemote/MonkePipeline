import os

from pxr import Usd, UsdGeom, Sdf, Kind
from OdenGraphQt import Port
from publisher.collector import CollectedAssetItem
from publisher.exporter.armature import ArmatureLayerExporter
from publisher.exporter.common import asset_root_path
from publisher.exporter.materials import MaterialsLayerExporter
from publisher.exporter.mesh import MeshLayerExporter
from publisher.exporter.usd_exporter import UsdExporter
from utils.monke_logging import get_logger
from templates.templates import Templates


logger = get_logger(__name__)
ASSETS_PRIM_PATH = "/Assets"
UP_AXES = {
    "y": UsdGeom.Tokens.y,
    "z": UsdGeom.Tokens.z
}


class ArmatureToIssacSimExecutor:
    """
    Execution logic for Armature to Isaac Sim node
    """
    def __init__(self, node):
        self.node = node

    def execute(self):
        armature_node = self.node.get_connected_armature_node()
        if not armature_node:
            logger.warning(f"Node '{self.node.name()}' has no connected armature node, skipping")
            return None

        collected_item : CollectedAssetItem = armature_node.collected_item
        if not collected_item:
            logger.warning(f"Node '{armature_node.name()}' has no collected asset, skipping")
            return None

        settings = armature_node.get_export_settings()
        meter_per_unit = settings["meter_per_unit"]
        mesh_scale = settings["mesh_scale"]

        exporter = ArmatureLayerExporter(meter_per_unit, mesh_scale)
        exporter.write_isaac_sim_data(collected_item)


class UsdOutputExecutor:
    """
    Execution logic for USD output node
    """
    def __init__(self, node):
        output_path = node.get_property("output_path")
        self.output_format = node.get_property("export_format")
        self.output_path = f"{output_path}.{self.output_format}" if output_path else None
        # stage is created on disk with the first written data, exporters write
        # variant and binding layers next to it so it can't live only in memory
        self.stage = None
        self.node = node
        self.templates = Templates()
        self.assets_main_prims = {}
        self.stage_settings = None

    def execute(self):
        if not self.output_path:
            logger.error(f"Node '{self.node.name()}' has no output path, skipping")
            return None
        if self.output_format == "usdz":
            logger.error(f"Node '{self.node.name()}': usdz export is not supported yet, skipping")
            return None

        for input_port in self.node.input_ports():
            self._execute_input_ports(input_port)

        if not self.stage:
            logger.info(f"Node '{self.node.name()}' has no data to export")
            return None

        self._group_assets()
        self._set_stage_settings()
        # grouping assets also changes sublayers (material binding layers)
        for layer in self.stage.GetLayerStack(includeSessionLayers=False):
            layer.Save()
        logger.info(f"Layer saved: {self.output_path}")
        return self.output_path

    def _execute_input_ports(self, input_port : Port):
        # handle USD data input ports
        if input_port.name().startswith("data"):
            for connected_port in input_port.connected_ports():
                connected_node = connected_port.node()
                if connected_node.type_ == "nodes.asset.AssetNode":
                    self._execute_asset_data(connected_node, connected_port)
                else:
                    pass # TODO handle other data types lie sublayers

    def _execute_asset_data(self, connected_node, connected_port):
        """
        handle asset data, write data of connected port into this node layer
        """
        collected_item : CollectedAssetItem = connected_node.collected_item
        if not collected_item:
            logger.warning(f"Node '{connected_node.name()}' has no collected asset, skipping")
            return

        connected_port_name = connected_port.name()
        asset_name = collected_item.name
        settings = connected_node.get_export_settings()
        if connected_port_name == "armature" and not connected_node.has_skeleton:
            logger.warning(f"Asset '{asset_name}' has no armature data, skipping armature export")
            return

        layer_exporter = self._create_layer_exporter(connected_port_name, asset_name, settings)
        if not layer_exporter:
            logger.warning(f"Exporting '{connected_port_name}' data is not supported yet, skipping '{asset_name}'")
            return

        self._update_stage_settings(connected_node, settings)
        if asset_name not in self.assets_main_prims:
            self._create_asset_main_prim(asset_name)

        logger.debug(f"Write '{connected_port_name}' data of '{asset_name}' into layer: {self.output_path}")
        layer_exporter.write(self._get_stage(), collected_item)

    def _create_layer_exporter(self, port_name, asset_name, settings):
        meter_per_unit = settings["meter_per_unit"]
        mesh_scale = settings["mesh_scale"]

        if port_name == "geometry":
            base_fields = self._get_asset_fields(asset_name)
            variants_template = self.templates.get_template_by_name("asset_mesh_variants_output")
            variants_dir = self.templates.resolve_template(variants_template, dict(base_fields))
            return MeshLayerExporter(
                base_fields, variants_dir, meter_per_unit, mesh_scale, settings["write_lod_to_sublayers"]
            )

        if port_name == "look":
            textures_template = self.templates.get_template_by_name("asset_textures_output")
            textures_dir = self.templates.resolve_template(textures_template, self._get_asset_fields(asset_name))
            return MaterialsLayerExporter(textures_dir, meter_per_unit)

        if port_name == "armature":
            return ArmatureLayerExporter(meter_per_unit, mesh_scale)

        return None # TODO physic

    def _get_asset_fields(self, asset_name):
        project_name = os.environ.get("PROJECTNAME")
        if not project_name:
            err = "There is no 'PROJECTNAME' environment variable"
            logger.error(err)
            raise RuntimeError(err)
        return {
            "ext": self.output_format,
            "project_name": project_name,
            "name": asset_name
        }

    def _get_stage(self):
        if not self.stage:
            logger.debug(f"Create layer: {self.output_path}")
            self.stage = Usd.Stage.CreateNew(self.output_path)
        return self.stage

    def _update_stage_settings(self, asset_node, settings):
        """
        up axis and meters per unit are layer metadata, so the first asset decides about them
        """
        if not self.stage_settings:
            self.stage_settings = settings
            return

        for key in ("up_axis", "meter_per_unit"):
            if settings[key] != self.stage_settings[key]:
                logger.warning(
                    f"Node '{asset_node.name()}' {key}: {settings[key]} differs from {self.stage_settings[key]} "
                    f"used for layer: {self.output_path}"
                )

    def _set_stage_settings(self):
        UsdExporter._set_fps(self.stage)
        UsdExporter._set_metadata(self.stage)
        UsdGeom.SetStageUpAxis(self.stage, UP_AXES.get(self.stage_settings["up_axis"], UsdGeom.Tokens.z))
        UsdGeom.SetStageMetersPerUnit(self.stage, self.stage_settings["meter_per_unit"])

    def _create_asset_main_prim(self, asset_name):
        # exporters always write asset data under '/<asset_name>', if layer gets more than one
        # asset they are moved under "Assets" prim when all data is written, see _group_assets
        main_xform_path = asset_root_path(asset_name)
        UsdGeom.Xform.Define(self._get_stage(), main_xform_path)

        # get and set asset main prim
        main_prim = self.stage.GetPrimAtPath(main_xform_path)
        main_prim.SetKind(Kind.Tokens.component)

        self.assets_main_prims[asset_name] = main_prim
        return main_prim

    def _group_assets(self):
        # here we need assume that if there is more than one asset all of them should be under "Assets" prim
        if len(self.assets_main_prims) == 1:
            main_prim = next(iter(self.assets_main_prims.values()))
            self.stage.SetDefaultPrim(main_prim)
            return

        assets_scope = UsdGeom.Scope.Define(self.stage, ASSETS_PRIM_PATH)
        assets_prim = assets_scope.GetPrim()
        assets_prim.SetKind(Kind.Tokens.assembly)
        self.stage.SetDefaultPrim(assets_prim)

        for asset_name in list(self.assets_main_prims):
            current_prim_path = Sdf.Path(asset_root_path(asset_name))
            new_path = assets_prim.GetPath().AppendChild(current_prim_path.name)
            # material binding sublayers hold overs for the asset too
            for layer in self.stage.GetLayerStack(includeSessionLayers=False):
                self._move_prim_spec(layer, current_prim_path, new_path)
            self.assets_main_prims[asset_name] = self.stage.GetPrimAtPath(new_path)

    @staticmethod
    def _move_prim_spec(layer, current_path, new_path):
        """
        Usd.NamespaceEditor doesn't fix relationship targets authored inside variants
        (material variants bindings), Sdf.CopySpec remaps all of them
        """
        if not layer.GetPrimAtPath(current_path):
            return
        Sdf.CreatePrimInLayer(layer, new_path.GetParentPath())
        Sdf.CopySpec(layer, current_path, layer, new_path)
        namespace_edit = Sdf.BatchNamespaceEdit()
        namespace_edit.Add(Sdf.NamespaceEdit.Remove(current_path))
        layer.Apply(namespace_edit)

import os

from pxr import Usd, UsdGeom, Kind
from exporter.layers_exporters.armature import ArmatureLayerExporter
from exporter.layers_exporters.common import FPS, sanitize_name
from exporter.layers_exporters.materials import MaterialsLayerExporter
from exporter.layers_exporters.mesh import MeshLayerExporter
from exporter.layers_exporters.physics import PhysicsLayerExporter
from templates.templates import Templates
from exporter.monke_logging import get_logger


logger = get_logger(__name__)

# how the main file references its geom/look/rig sublayers
SUBLAYER_RESOLVER_MONKE = "MonkeResolver"
SUBLAYER_RESOLVER_DEFAULT = "Default"
SUBLAYER_RESOLVERS = (SUBLAYER_RESOLVER_MONKE, SUBLAYER_RESOLVER_DEFAULT)


class UsdExporter:
    def __init__(self, settings):
        self.up_axis = {
            "y": UsdGeom.Tokens.y,
            "z": UsdGeom.Tokens.z
        }.get(settings["up_axis"], UsdGeom.Tokens.z)
        self.extension = settings["extension"]
        self.meter_per_unit = settings["meter_per_unit"]
        self.mesh_scale = settings.get("mesh_scale", 1.0)
        self.export_geom = settings["export_geometry"]
        self.export_mat = settings["export_materials"]
        self.export_armature = settings["export_armature"]
        self.export_physics = settings["export_physics"]
        self.projects_root = settings["projects_root"]
        self.project_name = settings["project_name"]
        self.sublayer_resolver = settings.get("sublayer_resolver", SUBLAYER_RESOLVER_DEFAULT)
        if not self.projects_root or not self.project_name:
            err = "No output folder set: save the .blend file or choose an output folder"
            logger.error(err)
            raise RuntimeError(err)

    def export(self, asset_item):
        asset_name = asset_item.name
        fields = {
            "ext": self.extension,
            "projects_root": self.projects_root,
            "project_name": self.project_name,
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
        fields["step"] = "physics"
        physics_file_path = templates.get_new_file_path(sublayer_file_template, fields)
        mesh_variants_output = templates.get_new_file_path(mesh_variants_template, fields)
        textures_output = templates.get_new_file_path(textures_template, fields)
        layer_paths_dict = {
            "geom": None,
            "look": None,
            "rig": None,
        }

        if self.export_physics:
            physics_exporter = PhysicsLayerExporter(asset_name, physics_file_path)
        else:
            physics_exporter = None

        if self.export_geom:
            variant_base_fields = {
                "ext": fields["ext"],
                "projects_root": fields["projects_root"],
                "project_name": fields["project_name"],
                "name": fields["name"],
            }
            mesh_exporter = MeshLayerExporter(variant_base_fields, mesh_variants_output, self.meter_per_unit, self.mesh_scale, physics_exporter)
            self._write_layer(geom_file_path, mesh_exporter, asset_item)
            layer_paths_dict["geom"] = geom_file_path

        if self.export_mat:
            materials_exporter = MaterialsLayerExporter(textures_output, self.meter_per_unit)
            self._write_layer(look_file_path, materials_exporter, asset_item)
            layer_paths_dict["look"] = look_file_path

        if self.export_armature:
            armature_exporter = ArmatureLayerExporter(self.meter_per_unit, self.mesh_scale)
            self._write_layer(rig_file_path, armature_exporter, asset_item)
            layer_paths_dict["rig"] = rig_file_path

        # creating main stage
        os.makedirs(os.path.dirname(main_file_path), exist_ok=True)
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
        step_order = ("geom", "look", "rig")
        main_dir = os.path.dirname(main_file_path)

        final_sublayers = []
        for step in step_order:
            layer_path = layer_paths_dict[step]
            if not layer_path:
                # step not exported this run: point at its newest version on disk,
                # so the main file never keeps a stale or other-resolver entry
                layer_path = templates.get_latest_file_path(sublayer_file_template, dict(fields, step=step))
            if not layer_path:
                continue
            final_sublayers.append(self._sublayer_asset_path(templates, sublayer_file_template, layer_path, main_dir))

        if self.export_physics:
            final_sublayers.append(physics_file_path)
            
        root_layer.subLayerPaths = final_sublayers
        root_layer.Save()

        return main_file_path

    def _sublayer_asset_path(self, templates, sublayer_file_template, layer_path, main_dir):
        if self.sublayer_resolver == SUBLAYER_RESOLVER_MONKE:
            # ":latest" lets the resolver pick the newest version at load time
            return templates.convert_path_to_monkedDisc(sublayer_file_template, layer_path)
        # plain path relative to the main file: loads in any app without the resolver plugin,
        # and the main file is rewritten on every export so it carries the newest versions
        rel_path = os.path.relpath(layer_path, main_dir)
        return rel_path if rel_path.startswith(".") else f"./{rel_path}"

    def _write_layer(self, file_path, layer_exporter, asset_item):
        logger.debug(f"Write layer: {file_path} for asset: {asset_item.name }")
        stage = layer_exporter.export(file_path, asset_item)
        if stage:
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

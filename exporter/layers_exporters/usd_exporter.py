import math
import os

from pxr import Usd, UsdGeom, Kind, Gf, Sdf, UsdPhysics
from exporter.layers_exporters.armature import ArmatureLayerExporter
from exporter.layers_exporters.common import (
    FPS,
    WORLD_ROOT_PATH,
    define_world_groups,
    sanitize_name,
    set_stage_metrics,
    unique_child_path,
)
from exporter.layers_exporters.lights import LightsLayerExporter
from exporter.layers_exporters.materials import MaterialsLayerExporter
from exporter.layers_exporters.mesh import MeshLayerExporter
from exporter.layers_exporters.physics import PhysicsLayerExporter
from templates.templates import Templates
from exporter.monke_logging import get_logger


logger = get_logger(__name__)

SUBLAYER_RESOLVER_MONKE = "MonkeResolver"
SUBLAYER_RESOLVER_DEFAULT = "Default"
SUBLAYER_RESOLVERS = (SUBLAYER_RESOLVER_MONKE, SUBLAYER_RESOLVER_DEFAULT)
REFERENCE_PREFIX = "REF"
INSTANCE_PREFIX = "INST"


class UsdExporter:
    def __init__(self, settings):
        self.templates = Templates()
        self.up_axis = {
            "y": UsdGeom.Tokens.y,
            "z": UsdGeom.Tokens.z
        }.get(settings["up_axis"], UsdGeom.Tokens.z)
        self.extension = settings["extension"]
        self.meter_per_unit = settings["meter_per_unit"]
        self.mesh_scale = settings.get("mesh_scale", 1.0)
        self.light_exposure_offset = settings.get("light_exposure_offset", 0.0)
        self.export_geom = settings["export_geometry"]
        self.export_mat = settings["export_materials"]
        self.export_armature = settings["export_armature"]
        self.export_physics = settings["export_physics"]
        self.projects_root = settings["projects_root"]
        self.project_name = settings["project_name"]
        self.world_collection = settings["collected_world_item"]
        self.export_lights = settings.get("export_lights", False)
        self.light_items = settings.get("collected_lights") or []
        self.world_sublayer_template = self.templates.get_template_by_name("world_sublayer_file")
        self.sublayer_resolver = settings.get("sublayer_resolver", SUBLAYER_RESOLVER_DEFAULT)
        if not self.projects_root or not self.project_name:
            err = "No output folder set: save the .blend file or choose an output folder"
            logger.error(err)
            raise RuntimeError(err)

    def export_world(self, name=""):
        if not self.world_collection and not self.light_items:
            return None

        fields = {
            "ext": self.extension,
            "projects_root": self.projects_root,
            "project_name": self.project_name,
            "name": name
        }

        asset_main_template = self.templates.get_template_by_name("asset_main_file")
        world_main_template = self.templates.get_template_by_name("world_main_file")
        world_main_path = self.templates.resolve_template(world_main_template, fields)
        world_main_dir = os.path.dirname(world_main_path)

        stage = Usd.Stage.CreateNew(world_main_path)
        self._set_fps(stage)
        self._set_metadata(stage)
        set_stage_metrics(stage, self.meter_per_unit, self.up_axis)

        root_prim = UsdGeom.Xform.Define(stage, WORLD_ROOT_PATH).GetPrim()
        root_prim.SetKind(Kind.Tokens.group)
        stage.SetDefaultPrim(root_prim)
        assets_ref_class = stage.CreateClassPrim(f"{WORLD_ROOT_PATH}/__assets")
        # asset reference prim path -> scale converting that asset into the world's units
        unit_scales = {}

        for collection_path, instancer_items_list in (self.world_collection or {}).items():
            group_path = define_world_groups(stage, collection_path)

            for instancer_item in instancer_items_list:
                if instancer_item.asset_name is None:
                    logger.warning(f"Skipping {instancer_item}: the instanced mesh is not under an asset collection")
                    continue

                asset_prim_name = sanitize_name(instancer_item.asset_name)
                asset_file_ref_path = assets_ref_class.GetPath().AppendChild(asset_prim_name)
                if not stage.GetPrimAtPath(asset_file_ref_path):
                    asset_ref_prim = stage.DefinePrim(asset_file_ref_path, "Xform")
                    fields["name"] = instancer_item.asset_name
                    asset_file_path = self.templates.resolve_template(asset_main_template, fields)
                    unit_scales[asset_file_ref_path] = self._asset_unit_scale(asset_file_path, instancer_item.asset_name)
                    asset_rel_path = os.path.relpath(asset_file_path, world_main_dir)
                    logger.debug(f"World references asset {instancer_item.asset_name} from {asset_rel_path}")
                    asset_ref_prim.GetReferences().AddReference(
                        assetPath=f"./{asset_rel_path}",
                        position=Usd.ListPositionFrontOfPrependList
                    )

                # placements with no matching point empty, or several instancers in one
                instance_name = sanitize_name(instancer_item.point_name or asset_prim_name)
                instance_path = unique_child_path(stage, group_path, instance_name)
                instance_prim = UsdGeom.Xform.Define(stage, instance_path).GetPrim()
                instance_prim.GetReferences().AddInternalReference(
                    asset_file_ref_path,
                    position=Usd.ListPositionFrontOfPrependList
                )

                if instancer_item.instancer_name.startswith(INSTANCE_PREFIX):
                    instance_prim.SetInstanceable(True)
                elif instancer_item.instancer_name.startswith(REFERENCE_PREFIX):
                    instance_prim.SetInstanceable(False)

                self._set_instance_transform(instance_prim, instancer_item, unit_scales[asset_file_ref_path])

        # set physics scene
        if self.export_physics:
            UsdPhysics.Scene.Define(stage, f"{WORLD_ROOT_PATH}/physicsScene")

        root_layer = stage.GetRootLayer()
        lights_path = self._export_lights_layer(fields)
        root_layer.subLayerPaths = [
            self._sublayer_asset_path(self.templates, self.world_sublayer_template, lights_path, world_main_dir)
        ] if lights_path else []

        root_layer.Save()
        return world_main_path

    def _export_lights_layer(self, fields):
        """
        writes a new version of the lights layer and returns its path. With lights not
        selected it returns the newest version on disk, so the world file keeps its lights
        """
        lights_fields = dict(fields, step="lights")
        if not self.export_lights:
            return self.templates.get_latest_file_path(self.world_sublayer_template, lights_fields)

        lights_stage = LightsLayerExporter(
            self.meter_per_unit, self.mesh_scale, self.up_axis, self.light_exposure_offset
        ).export(self.light_items)
        if not lights_stage:
            return None

        lights_path = self.templates.get_new_file_path(self.world_sublayer_template, lights_fields)
        os.makedirs(os.path.dirname(lights_path), exist_ok=True)
        lights_layer = lights_stage.GetRootLayer()
        self._set_metadata(lights_stage)
        # the stage is in memory, so it's written with Export instead of Save
        lights_layer.Export(lights_path)
        logger.info(f"Exported {len(self.light_items)} lights to {lights_path}")
        return lights_path

    def _asset_unit_scale(self, asset_file_path, asset_name):
        """
        scale that converts a referenced asset into the world's units. USD reads metersPerUnit
        and upAxis only from the root layer and never converts referenced data, so an asset
        exported with other settings would come in at the wrong size.
        """
        layer = Sdf.Layer.FindOrOpen(asset_file_path) if os.path.exists(asset_file_path) else None
        if layer is None:
            logger.warning(f"World references asset '{asset_name}', which isn't exported yet: {asset_file_path}")
            return 1.0

        # files without the metadata are read with USD's fallbacks
        root = layer.pseudoRoot
        asset_meters = root.GetInfo("metersPerUnit") if root.HasInfo("metersPerUnit") else UsdGeom.LinearUnits.centimeters
        asset_up_axis = root.GetInfo("upAxis") if root.HasInfo("upAxis") else UsdGeom.GetFallbackUpAxis()

        if asset_up_axis != self.up_axis:
            logger.warning(
                f"Asset '{asset_name}' is {asset_up_axis}-up but the world is {self.up_axis}-up. "
                "Re-export the asset with the same up axis, it isn't rotated to match"
            )

        unit_scale = asset_meters / self.meter_per_unit
        if not math.isclose(unit_scale, 1.0, rel_tol=1e-6):
            logger.warning(
                f"Asset '{asset_name}' uses metersPerUnit {asset_meters:g}, the world uses {self.meter_per_unit:g}. "
                f"Its placements get an extra scale of {unit_scale:g}"
            )
        return unit_scale

    def _set_instance_transform(self, prim, instancer_item, unit_scale=1.0):
        rot, loc, scale = instancer_item.decompose_transform()
        xform_api = UsdGeom.XformCommonAPI(prim)
        xform_api.SetTranslate(Gf.Vec3d(loc.x, loc.y, loc.z) * self.mesh_scale)
        xform_api.SetRotate(
            Gf.Vec3f(math.degrees(rot.x), math.degrees(rot.y), math.degrees(rot.z)),
            UsdGeom.XformCommonAPI.RotationOrderXYZ
        )
        # unit_scale converts an asset authored in other units, the translation is already in world units
        xform_api.SetScale(Gf.Vec3f(scale.x, scale.y, scale.z) * unit_scale)


    def export_assets(self, asset_item):
        asset_name = asset_item.name
        fields = {
            "ext": self.extension,
            "projects_root": self.projects_root,
            "project_name": self.project_name,
            "name": asset_name
        }
        asset_main_file_template = self.templates.get_template_by_name("asset_main_file")
        sublayer_file_template = self.templates.get_template_by_name("asset_sublayer_file")
        mesh_variants_template = self.templates.get_template_by_name("asset_mesh_variants_output")
        textures_template = self.templates.get_template_by_name("asset_textures_output")

        main_file_path = self.templates.resolve_template(asset_main_file_template, fields)
        fields["step"] = "geom"
        geom_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "look"
        look_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "rig"
        rig_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        fields["step"] = "physics"
        physics_file_path = self.templates.get_new_file_path(sublayer_file_template, fields)
        mesh_variants_output = self.templates.get_new_file_path(mesh_variants_template, fields)
        textures_output = self.templates.get_new_file_path(textures_template, fields)
        layer_paths_dict = {
            "geom": None,
            "look": None,
            "rig": None,
            "physics": None,
        }

        physics_exporter = None
        if self.export_physics and not self.export_geom:
            logger.warning("Physics export needs geometry export: rigid bodies are read from the exported meshes")
        elif self.export_physics and asset_item.has_physics:
            physics_exporter = PhysicsLayerExporter(
                asset_name, physics_file_path, self.meter_per_unit, self.mesh_scale, self.up_axis
            )

        if self.export_geom and asset_item.has_geometry:
            variant_base_fields = {
                "ext": fields["ext"],
                "projects_root": fields["projects_root"],
                "project_name": fields["project_name"],
                "name": fields["name"],
            }
            mesh_exporter = MeshLayerExporter(
                variant_base_fields, mesh_variants_output, self.meter_per_unit, self.mesh_scale, physics_exporter, self.up_axis
            )
            if self._write_layer(geom_file_path, mesh_exporter, asset_item):
                layer_paths_dict["geom"] = geom_file_path

        if physics_exporter:
            # joints need every rigid body, which the mesh export above has collected
            layer_paths_dict["physics"] = physics_exporter.save()

        if self.export_mat and asset_item.has_materials:
            materials_exporter = MaterialsLayerExporter(textures_output, self.meter_per_unit, self.up_axis)
            if self._write_layer(look_file_path, materials_exporter, asset_item):
                layer_paths_dict["look"] = look_file_path

        if self.export_armature and asset_item.has_armature:
            armature_exporter = ArmatureLayerExporter(self.meter_per_unit, self.mesh_scale, self.up_axis)
            if self._write_layer(rig_file_path, armature_exporter, asset_item):
                layer_paths_dict["rig"] = rig_file_path

        # steps selected but with nothing written for this asset: the main file
        # gets no sublayer for them, not even an older version from disk
        selected_steps = {
            "geom": self.export_geom,
            "look": self.export_mat,
            "rig": self.export_armature,
            "physics": self.export_physics and self.export_geom,
        }
        empty_steps = {step for step, selected in selected_steps.items() if selected and not layer_paths_dict[step]}

        # creating main stage
        os.makedirs(os.path.dirname(main_file_path), exist_ok=True)
        if os.path.exists(main_file_path):
            main_stage = Usd.Stage.Open(main_file_path)
        else:
            main_stage = Usd.Stage.CreateNew(main_file_path)

        # stage settings
        self._set_fps(main_stage)
        self._set_metadata(main_stage)
        set_stage_metrics(main_stage, self.meter_per_unit, self.up_axis)

        # add main prim
        main_prim = main_stage.OverridePrim(f"/{sanitize_name(asset_name)}")
        main_prim.SetKind(Kind.Tokens.component)
        main_stage.SetDefaultPrim(main_prim)

        # setting sublayers, strongest first
        root_layer = main_stage.GetRootLayer()
        step_order = ("geom", "look", "rig", "physics")
        main_dir = os.path.dirname(main_file_path)

        final_sublayers = []
        for step in step_order:
            if step in empty_steps:
                continue
            layer_path = layer_paths_dict[step]
            if not layer_path:
                # step not exported this run: point at its newest version on disk,
                # so the main file never keeps a stale or other-resolver entry
                layer_path = self.templates.get_latest_file_path(sublayer_file_template, dict(fields, step=step))
            if not layer_path:
                continue
            final_sublayers.append(self._sublayer_asset_path(self.templates, sublayer_file_template, layer_path, main_dir))

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
        """returns True when the exporter wrote a layer"""
        logger.debug(f"Write layer: {file_path} for asset: {asset_item.name }")
        stage = layer_exporter.export(file_path, asset_item)
        if not stage:
            return False
        self._set_fps(stage)
        stage.GetRootLayer().Save()
        return True

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

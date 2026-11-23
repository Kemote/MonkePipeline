import math

from pxr import Usd, UsdGeom, UsdLux, Gf, Kind
from exporter.layers_exporters.common import (
    WORLD_ROOT_PATH,
    define_world_groups,
    sanitize_name,
    set_stage_metrics,
    unique_child_path,
)
from exporter.monke_logging import get_logger


logger = get_logger(__name__)


class LightsLayerExporter:
    """
    authors the collected lights as UsdLux prims into an in-memory layer, under the same
    /World/<collection path> groups the world layout uses. The caller writes it with Export().

    Units follow Blender's own USD exporter, so both give the same file:
    - normalize is on, as Blender keeps a light's power when its size changes
    - point, spot and area power (W) -> intensity W / pi
    - sun strength -> intensity strength / 4
    - sun angle and spot size are full angles in Blender, UsdLux wants half angles
    """

    def __init__(self, meter_per_unit, mesh_scale=1.0, up_axis=UsdGeom.Tokens.z):
        self.meter_per_unit = meter_per_unit
        self.mesh_scale = mesh_scale
        self.up_axis = up_axis

    def export(self, light_items):
        """returns the in-memory stage, or None when there are no lights"""
        if not light_items:
            return None

        stage = Usd.Stage.CreateInMemory()
        set_stage_metrics(stage, self.meter_per_unit, self.up_axis)
        root_prim = UsdGeom.Xform.Define(stage, WORLD_ROOT_PATH).GetPrim()
        root_prim.SetKind(Kind.Tokens.group)
        stage.SetDefaultPrim(root_prim)

        for light_item in light_items:
            # same groups as the world layout, so lights sit next to the instances
            parent_path = define_world_groups(stage, light_item.collection_path)
            light_path = unique_child_path(stage, parent_path, sanitize_name(light_item.name))
            light = self._define_light(stage, light_path, light_item)
            self._set_common_inputs(light, light_item)
            self._set_transform(light.GetPrim(), light_item.matrix_world)
            logger.debug(f"Exported {light_item} as {light_path}")

        return stage

    def _define_light(self, stage, path, light_item):
        size_scale = self.mesh_scale

        if light_item.light_type == "SUN":
            light = UsdLux.DistantLight.Define(stage, path)
            light.CreateIntensityAttr(light_item.energy / 4.0)
            light.CreateAngleAttr(math.degrees(light_item.angle) / 2.0)
            return light

        if light_item.light_type == "AREA":
            if light_item.shape in ("DISK", "ELLIPSE"):
                light = UsdLux.DiskLight.Define(stage, path)
                light.CreateRadiusAttr(light_item.size / 2.0 * size_scale)
            else:
                light = UsdLux.RectLight.Define(stage, path)
                height = light_item.size_y if light_item.shape == "RECTANGLE" else light_item.size
                light.CreateWidthAttr(light_item.size * size_scale)
                light.CreateHeightAttr(height * size_scale)
            light.CreateIntensityAttr(light_item.energy / math.pi)
            return light

        # POINT and SPOT
        light = UsdLux.SphereLight.Define(stage, path)
        light.CreateIntensityAttr(light_item.energy / math.pi)
        radius = light_item.radius * size_scale
        light.CreateRadiusAttr(radius)
        if radius == 0.0:
            light.CreateTreatAsPointAttr(True)

        if light_item.light_type == "SPOT":
            shaping = UsdLux.ShapingAPI.Apply(light.GetPrim())
            shaping.CreateShapingConeAngleAttr(math.degrees(light_item.spot_size) / 2.0)
            shaping.CreateShapingConeSoftnessAttr(light_item.spot_blend)
        return light

    @staticmethod
    def _set_common_inputs(light, light_item):
        light.CreateNormalizeAttr(True)
        light.CreateColorAttr(Gf.Vec3f(*light_item.color))
        if light_item.exposure:
            light.CreateExposureAttr(light_item.exposure)
        if light_item.use_temperature:
            light.CreateEnableColorTemperatureAttr(True)
            light.CreateColorTemperatureAttr(light_item.temperature)
        if light_item.diffuse_factor != 1.0:
            light.CreateDiffuseAttr(light_item.diffuse_factor)
        if light_item.specular_factor != 1.0:
            light.CreateSpecularAttr(light_item.specular_factor)
        if not light_item.use_shadow:
            UsdLux.ShadowAPI.Apply(light.GetPrim()).CreateShadowEnableAttr(False)

    def _set_transform(self, prim, matrix_world):
        # translate/rotate/scale ops instead of one matrix, so lights stay easy to move in other apps
        location, rotation, scale = matrix_world.decompose()
        euler = rotation.to_euler("XYZ")
        xform_api = UsdGeom.XformCommonAPI(prim)
        xform_api.SetTranslate(Gf.Vec3d(*location) * self.mesh_scale)
        # Blender eulers are radians, USD rotate ops are degrees, both apply X first
        xform_api.SetRotate(
            Gf.Vec3f(*(math.degrees(angle) for angle in euler)),
            UsdGeom.XformCommonAPI.RotationOrderXYZ
        )
        xform_api.SetScale(Gf.Vec3f(*scale))


import os

from pxr import Usd, UsdGeom, UsdShade, Sdf
from publisher.exporter.common import (
    asset_root_path,
    base_material_name,
    looks_scope_path,
    material_prim_name,
    mesh_prim_path,
    sanitize_name,
)
from publisher.monke_logging import get_logger


logger = get_logger(__name__)


class MaterialBindingLayerExporter:
    """
    create a separate layer next to the geometry file for binding data
    """

    def __init__(self, meter_per_unit):
        self.meter_per_unit = meter_per_unit

    def write_for_layer(self, geo_layer_path, asset_item, outliner_paths, has_skeleton=False):
        base_path, extension = os.path.splitext(geo_layer_path)
        binding_layer_path = f"{base_path}_binding{extension}"

        stage = Usd.Stage.CreateNew(binding_layer_path)
        UsdGeom.SetStageMetersPerUnit(stage, self.meter_per_unit)
        self.export(stage, asset_item, outliner_paths, has_skeleton)
        stage.GetRootLayer().Save()
        return binding_layer_path

    def export(self, stage, asset_item, outliner_paths, has_skeleton=False):
        logger.debug("Exporting materials binding...")
        looks_path = looks_scope_path(asset_item.name, has_skeleton)
        variant_bindings = {}

        for outliner_path in outliner_paths:
            mesh_obj = asset_item.mesh_objects[outliner_path]
            materials = self._used_materials(mesh_obj)
            if not materials:
                continue

            prim_path = mesh_prim_path(asset_item.name, asset_item.path, outliner_path, has_skeleton)
            over_prim = stage.OverridePrim(prim_path)
            binding_api = UsdShade.MaterialBindingAPI.Apply(over_prim)

            if len(materials) == 1:
                _, material = materials[0]
                self._add_binding(over_prim, looks_path, material, variant_bindings)
            else:
                self._bind_subsets(binding_api, mesh_obj, materials, looks_path, variant_bindings)

        self._author_variant_bindings(stage, asset_item, looks_path, variant_bindings, has_skeleton)

    @staticmethod
    def _used_materials(mesh_obj):
        used_indices = sorted({polygon.material_index for polygon in mesh_obj.data.polygons})
        materials = []
        for index in used_indices:
            if index < len(mesh_obj.material_slots) and mesh_obj.material_slots[index].material:
                materials.append((index, mesh_obj.material_slots[index].material))
        return materials

    def _bind_subsets(self, binding_api, mesh_obj, materials, looks_path, variant_bindings):
        for material_index, material in materials:
            face_indices = [
                i for i, polygon in enumerate(mesh_obj.data.polygons)
                if polygon.material_index == material_index
            ]
            if not face_indices:
                continue

            # the subset is named after the base material
            subset = binding_api.CreateMaterialBindSubset(
                sanitize_name(base_material_name(material.name)), face_indices, elementType="face"
            )
            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim())
            self._add_binding(subset.GetPrim(), looks_path, material, variant_bindings)

        binding_api.SetMaterialBindSubsetsFamilyType(UsdGeom.Tokens.partition)

    def _add_binding(self, prim, looks_path, material, variant_bindings):
        base_name = base_material_name(material.name)
        if base_name != material.name:
            variant_bindings.setdefault(base_name, []).append(prim.GetPath())
        else:
            self._bind(prim, looks_path, material)

    def _author_variant_bindings(self, stage, asset_item, looks_path, variant_bindings, has_skeleton=False):
        if not variant_bindings:
            return

        root_prim = stage.OverridePrim(asset_root_path(asset_item.name, has_skeleton))
        for base_name, prim_paths in variant_bindings.items():
            variants = asset_item.material_variants.get(base_name)
            if not variants:
                continue

            variant_set = root_prim.GetVariantSets().AddVariantSet(base_name)
            for variant_name, material in variants.items():
                variant_set.AddVariant(variant_name)
                variant_set.SetVariantSelection(variant_name)
                with variant_set.GetVariantEditContext():
                    for prim_path in prim_paths:
                        self._bind(stage.GetPrimAtPath(prim_path), looks_path, material)

            variant_set.SetVariantSelection(next(iter(variants)))

    @staticmethod
    def _bind(prim, looks_path, material):
        material_path = f"{looks_path}/{material_prim_name(material.name)}"
        prim.CreateRelationship("material:binding", custom=False).SetTargets([Sdf.Path(material_path)])

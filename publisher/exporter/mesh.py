import os

import bpy
from pxr import Usd, UsdGeom, UsdSkel, Sdf, Gf
from publisher import collector
from publisher.exporter.armature import SkeletonBindingPlan
from publisher.exporter.common import (
    MAX_JOINT_INFLUENCES,
    asset_root_path,
    geom_scope_path,
    is_lod_set,
    local_skeleton_path,
    lod_purpose,
    mesh_prim_path,
    sanitize_name,
    scaled_matrix_to_gf,
    skel_root_path,
)
from templates.templates import Templates
from publisher.exporter.material_binding import MaterialBindingLayerExporter
from publisher.monke_logging import get_logger


logger = get_logger(__name__)


class MeshLayerExporter:
    """
    export provided asset mesh data, UV's, and it's variants
    """

    VARIANT_LAYER_TEMPLATE_NAME = "asset_mesh_variant_layer"

    def __init__(self, base_fields, variants_dir, meter_per_unit, mesh_scale=1.0, apply_modifiers=True):
        self.templates = Templates()
        self.base_fields = base_fields
        self.variant_layer_template = self.templates.get_template_by_name(self.VARIANT_LAYER_TEMPLATE_NAME)
        self.variants_dir = variants_dir
        self.meter_per_unit = meter_per_unit
        self.mesh_scale = mesh_scale
        self.apply_modifiers = apply_modifiers
        self._depsgraph = None
        self.binding_exporter = MaterialBindingLayerExporter(meter_per_unit)

    def export(self, output_path, asset_item):
        stage = Usd.Stage.CreateNew(output_path)
        UsdGeom.SetStageMetersPerUnit(stage, self.meter_per_unit)
        has_skeleton = bool(asset_item.armature_objects)
        if has_skeleton:
            UsdSkel.Root.Define(stage, skel_root_path(asset_item.name))

        UsdGeom.Xform.Define(stage, asset_root_path(asset_item.name, has_skeleton))
        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name, has_skeleton))
        skeleton_plan = SkeletonBindingPlan(asset_item) if has_skeleton else None

        root : collector.VariantNode = asset_item.variant_root
        self._write_meshes(stage, asset_item, root.outliner_paths, skeleton_plan, has_skeleton)
        self._attach_binding_layer(stage, asset_item, root.outliner_paths, has_skeleton)

        if root.variant_sets:
            asset_prim = stage.GetPrimAtPath(asset_root_path(asset_item.name, has_skeleton))
            stage = self._author_variant_sets(stage, asset_item, asset_prim, root.variant_sets, self.variants_dir, skeleton_plan)

        # promote variants when a skeleton causes the mesh prim path to change.
        if has_skeleton:
            asset_prim = stage.GetPrimAtPath(f"/{asset_item.name}")
            promoted_sets = asset_prim.GetVariantSets()
            if root.variant_sets:
                logger.debug("Promote meshes variants")
                self._promote_mesh_variants(stage, asset_item.name, promoted_sets, root)
            if asset_item.material_variants:
                logger.debug("Promote materials variants")
                self._promote_materials_variants(stage, asset_item, promoted_sets)

        return stage

    def _promote_mesh_variants(self, stage: Usd.Stage, asset_name, promoted_sets, variant_node):
        for variant_set_name, variants in variant_node.variant_sets.items():
            logger.debug(f"Promoted variant set: {variant_set_name}")
            if not variant_set_name.lower() == "lod":
                variant_set: Usd.VariantSet = promoted_sets.AddVariantSet(variant_set_name)
                for variant_data in self._promote_variants(stage, variants, variant_set, variant_set_name, asset_name):
                    self._promote_mesh_variants(stage, asset_name, promoted_sets, variant_data)
            else:
                for variant_data in variants.values():
                    self._promote_mesh_variants(stage, asset_name, promoted_sets, variant_data)

    def _promote_materials_variants(self, stage, asset_item, promoted_sets):
        for mat_set_name, variants_dict in asset_item.material_variants.items():
            logger.debug(f"Promoted variant set: {mat_set_name}")
            variant_set: Usd.VariantSet = promoted_sets.AddVariantSet(mat_set_name)
            for varaint_data in self._promote_variants(stage, variants_dict, variant_set, mat_set_name, asset_item.name):
                logger.debug("Material promoted")

    def _promote_variants(self, stage, variants_dict, variant_set, variant_set_name, asset_name):
            for variant_name, variant_data in variants_dict.items():
                logger.debug(f"Promote variant set: {variant_set_name}")
                variant_set.AddVariant(variant_name)
                variant_set.SetVariantSelection(variant_name)
                with variant_set.GetVariantEditContext():
                    over_prim = stage.OverridePrim((f"/{asset_name}/SkelRoot"))
                    logger.debug(f"Set variant selection to: {variant_name}")
                    over_variant_set = over_prim.GetVariantSets().AddVariantSet(variant_set_name)
                    over_variant_set.SetVariantSelection(variant_name)
                yield variant_data

    def _write_meshes(self, stage, asset_item, outliner_paths, skeleton_plan=None, has_skeleton=False, in_variant_layer=False):
        for outliner_path in outliner_paths:
            mesh = asset_item.mesh_objects[outliner_path]
            prim_path = mesh_prim_path(asset_item.name, asset_item.path, outliner_path, has_skeleton)
            binding = skeleton_plan.mesh_bindings.get(outliner_path) if skeleton_plan else None
            self._write_mesh(stage, prim_path, mesh, asset_item.name, binding, in_variant_layer)

    def _author_variant_sets(self,
                             stage: Usd.Stage,
                             asset_item: collector.CollectedAssetItem,
                             prim: Usd.Prim,
                             variant_sets,
                             variants_dir,
                             skeleton_plan=None,
                             variant_path=""):
        """
        authors variant sets from Blender collection names. 
        The "lod" set is the only exception: LODs use render purposes instead of standard USD variants.
        """
        os.makedirs(variants_dir, exist_ok=True)
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)

        variant_sets_api = prim.GetVariantSets()
        for set_name, variants in variant_sets.items():
            set_segment = sanitize_name(set_name)
            set_dir = os.path.join(variants_dir, set_segment)
            set_variant_path = os.path.join(variant_path, set_segment) if variant_path else set_segment
            os.makedirs(set_dir, exist_ok=True)

            if is_lod_set(set_name):
                for variant_name, node in variants.items():
                    lod_layer_path = self._write_variant_layer(
                        asset_item, set_dir, variant_name, node, set_variant_path, skeleton_plan, purpose=lod_purpose(variant_name)
                    )
                    prim.GetReferences().AddReference(os.path.relpath(lod_layer_path, stage_dir))
                continue

            variant_set = variant_sets_api.AddVariantSet(set_name)
            for variant_name, node in variants.items():
                variant_set.AddVariant(variant_name)
                variant_layer_path = self._write_variant_layer(asset_item, set_dir, variant_name, node, set_variant_path, skeleton_plan)
                variant_set.SetVariantSelection(variant_name)
                with variant_set.GetVariantEditContext():
                    prim.GetReferences().AddReference(os.path.relpath(variant_layer_path, stage_dir))
                    
            variant_set.SetVariantSelection(next(iter(variants)))
        return stage

    def _write_variant_layer(self, asset_item, set_dir, variant_name, node, variant_path, skeleton_plan=None, purpose=None):
        logger.debug(f"Writing variant layer: {variant_path}")
        fields = dict(self.base_fields)
        fields["variant_path"] = variant_path
        fields["variant"] = sanitize_name(variant_name)
        variant_layer_path = self.templates.get_new_file_path(self.variant_layer_template, fields)
        os.makedirs(os.path.dirname(variant_layer_path), exist_ok=True)
        variant_stage = Usd.Stage.CreateNew(variant_layer_path)
        UsdGeom.SetStageMetersPerUnit(variant_stage, self.meter_per_unit)
        UsdGeom.Xform.Define(variant_stage, asset_root_path(asset_item.name))
        UsdGeom.Scope.Define(variant_stage, geom_scope_path(asset_item.name))

        if purpose:
            # meshes inherit purpose from the parent prim path
            purpose_scope = UsdGeom.Scope.Define(
                variant_stage, f"{geom_scope_path(asset_item.name)}/{purpose}"
            )
            purpose_scope.CreatePurposeAttr().Set(purpose)

        self._write_meshes(variant_stage, asset_item, node.outliner_paths, skeleton_plan, in_variant_layer=True)
        self._attach_binding_layer(variant_stage, asset_item, node.outliner_paths)

        if node.variant_sets:
            asset_prim = variant_stage.GetPrimAtPath(asset_root_path(asset_item.name))
            variant_segment = sanitize_name(variant_name)
            nested_dir = os.path.join(set_dir, variant_segment)
            nested_variant_path = os.path.join(variant_path, variant_segment)
            self._author_variant_sets(
                variant_stage, asset_item, asset_prim, node.variant_sets, nested_dir, skeleton_plan, nested_variant_path
            )

        # a defaultPrim lets the parent layer reference this file without naming a prim
        variant_stage.GetRootLayer().defaultPrim = sanitize_name(asset_item.name)
        variant_stage.GetRootLayer().Save()
        return variant_layer_path

    def _attach_binding_layer(self, stage, asset_item, outliner_paths, has_skeleton=False):
        """
        create separate layer for material binding which is used for material variants,
        the binding file sits next to its geometry layer, so the relative path is just the name
        """
        if not outliner_paths:
            return
        geo_layer = stage.GetRootLayer()
        binding_layer_path = self.binding_exporter.write_for_layer(geo_layer.realPath, asset_item, outliner_paths, has_skeleton)
        geo_layer.subLayerPaths.append(os.path.basename(binding_layer_path))

    def _get_evaluated_object(self, mesh_obj):
        """
        returns the modifier-evaluated version of mesh_obj (as seen in the viewport) when
        apply_modifiers is enabled, without destructively applying anything to the source object
        """
        if not self.apply_modifiers or not mesh_obj.modifiers:
            return mesh_obj
        if self._depsgraph is None:
            self._depsgraph = bpy.context.evaluated_depsgraph_get()
        return mesh_obj.evaluated_get(self._depsgraph)

    def _write_mesh(self, stage, prim_path, mesh_obj, asset_name, skeleton_binding=None, in_variant_layer=False):
        usd_mesh = UsdGeom.Mesh.Define(stage, prim_path)
        eval_obj = self._get_evaluated_object(mesh_obj)
        mesh_data = eval_obj.data

        scale = self.mesh_scale
        usd_mesh.CreateFaceVertexCountsAttr([len(p.vertices) for p in mesh_data.polygons])
        usd_mesh.CreateFaceVertexIndicesAttr([idx for p in mesh_data.polygons for idx in p.vertices])
        usd_mesh.CreatePointsAttr(
            [Gf.Vec3f(v.co.x * scale, v.co.y * scale, v.co.z * scale) for v in mesh_data.vertices]
        )
        usd_mesh.AddTransformOp().Set(scaled_matrix_to_gf(mesh_obj.matrix_world, scale))

        if mesh_data.uv_layers.active:
            uv_attr = UsdGeom.PrimvarsAPI(usd_mesh).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
            )
            uv_attr.Set([Gf.Vec2f(uv.uv.x, uv.uv.y) for uv in mesh_data.uv_layers.active.data])

        if skeleton_binding:
            self._write_skin_binding(usd_mesh, eval_obj, mesh_obj, asset_name, skeleton_binding, scale, in_variant_layer)

    @staticmethod
    def _write_skin_binding(usd_mesh, eval_obj, mesh_obj, asset_name, skeleton_binding, mesh_scale, in_variant_layer=False):
        """
        create armature binding. eval_obj provides the vertices matching the geometry
        actually written to USD (which may be modifier-evaluated), while mesh_obj is the
        source object whose vertex group names are resolved against the skeleton's bones.
        """
        skeleton_path, bone_names = skeleton_binding
        if in_variant_layer:
            skeleton_path = local_skeleton_path(asset_name, skeleton_path)
        bone_index = {name: index for index, name in enumerate(bone_names)}

        binding_api = UsdSkel.BindingAPI.Apply(usd_mesh.GetPrim())
        binding_api.CreateSkeletonRel().SetTargets([Sdf.Path(skeleton_path)])

        indices, weights = MeshLayerExporter._per_vertex_weights(eval_obj, mesh_obj, bone_index)
        binding_api.CreateJointIndicesPrimvar(constant=False, elementSize=MAX_JOINT_INFLUENCES).Set(indices)
        binding_api.CreateJointWeightsPrimvar(constant=False, elementSize=MAX_JOINT_INFLUENCES).Set(weights)
        binding_api.CreateGeomBindTransformAttr().Set(scaled_matrix_to_gf(mesh_obj.matrix_world, mesh_scale))

    @staticmethod
    def _per_vertex_weights(eval_obj, mesh_obj, bone_index):
        indices = []
        weights = []
        for vertex in eval_obj.data.vertices:
            influences = sorted(
                (
                    (bone_index[mesh_obj.vertex_groups[group.group].name], group.weight)
                    for group in vertex.groups
                    if group.group < len(mesh_obj.vertex_groups)
                    and mesh_obj.vertex_groups[group.group].name in bone_index
                ),
                key=lambda pair: pair[1],
                reverse=True,
            )[:MAX_JOINT_INFLUENCES]

            total_weight = sum(weight for _, weight in influences) or 1.0
            pad = MAX_JOINT_INFLUENCES - len(influences)

            indices.extend([index for index, _ in influences] + [0] * pad)
            weights.extend([weight / total_weight for _, weight in influences] + [0.0] * pad)

        return indices, weights

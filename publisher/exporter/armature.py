from pxr import UsdGeom, UsdSkel, Usd
from publisher.exporter.common import (
    armature_scope_path,
    bone_ancestors,
    find_armature_modifier,
    sanitize_name,
    scaled_matrix_to_gf,
)
from publisher.monke_logging import get_logger


logger = get_logger(__name__)


class SkeletonBindingPlan:
    """
    one Skeleton prim per armature, shared by every mesh (across all variants and LOD
    purposes) that is skinned to it - variants only ever change geometry, never the rig.
    """

    def __init__(self, asset_item):
        self.asset_item = asset_item
        self.skeletons = {}
        self.mesh_bindings = {}

        for armature_obj in asset_item.armature_objects.values():
            self._plan_armature(armature_obj)

    def _plan_armature(self, armature_obj):
        skeleton_name = sanitize_name(armature_obj.name)
        skeleton_path = f"{armature_scope_path(self.asset_item.name, True)}/{skeleton_name}"

        all_outliner_paths = self._all_outliner_paths(self.asset_item.variant_root)
        bones = self._bones_for(armature_obj, all_outliner_paths)
        if not bones:
            logger.warning(
                f"Armature '{armature_obj.name}' has no meshes skinned to it - it will not be exported. "
                "Check that a mesh has an Armature modifier pointing at it, and that its vertex "
                "group names exactly match the armature's bone names."
            )
            return

        self.skeletons[skeleton_path] = (armature_obj, bones)
        self._bind_meshes(armature_obj, all_outliner_paths, skeleton_path, bones)

    def _all_outliner_paths(self, node):
        paths = list(node.outliner_paths)
        for variants in node.variant_sets.values():
            for child in variants.values():
                paths.extend(self._all_outliner_paths(child))
        return paths

    def _bind_meshes(self, armature_obj, outliner_paths, skeleton_path, bone_names):
        for outliner_path in outliner_paths:
            if self._used_bones(armature_obj, outliner_path):
                self.mesh_bindings[outliner_path] = (skeleton_path, bone_names)

    def _bones_for(self, armature_obj, outliner_paths):
        used = set()
        for outliner_path in outliner_paths:
            used.update(self._used_bones(armature_obj, outliner_path))

        expanded = set(used)
        for bone_name in used:
            for ancestor in bone_ancestors(armature_obj.data.bones[bone_name]):
                expanded.add(ancestor.name)

        return [bone.name for bone in armature_obj.data.bones if bone.name in expanded]

    def _used_bones(self, armature_obj, outliner_path):
        mesh_obj = self.asset_item.mesh_objects.get(outliner_path)
        if mesh_obj is None or find_armature_modifier(mesh_obj, {armature_obj}) is None:
            return set()
        bone_names = {bone.name for bone in armature_obj.data.bones}
        return {group.name for group in mesh_obj.vertex_groups if group.name in bone_names}


class ArmatureLayerExporter:
    """
    export one static bind-pose skeleton per armature, shared across all variants
    """

    def __init__(self, meter_per_unit, mesh_scale=1.0):
        self.meter_per_unit = meter_per_unit
        self.mesh_scale = mesh_scale

    def export(self, output_path, asset_item):
        stage = Usd.Stage.CreateNew(output_path)
        UsdGeom.SetStageMetersPerUnit(stage, self.meter_per_unit)
        if not asset_item.armature_objects:
            return None

        plan = SkeletonBindingPlan(asset_item)
        if not plan.skeletons:
            logger.warning(f"No skeleton bindings found for asset '{asset_item.name}' - skipping armature layer.")
            return None

        UsdGeom.Scope.Define(stage, armature_scope_path(asset_item.name, True))
        for skeleton_path, (armature_obj, bone_names) in plan.skeletons.items():
            self._write_skeleton(stage, skeleton_path, armature_obj, bone_names)
        return stage
    
    def _write_skeleton(self, stage, skeleton_path, armature_obj, bone_names):
        skeleton = UsdSkel.Skeleton.Define(stage, skeleton_path)
        bones = [armature_obj.data.bones[name] for name in bone_names]
        # UsdSkel requires a joint's parent to precede it in the joints array
        bones.sort(key=lambda bone: len(bone_ancestors(bone)))

        joint_tokens = {}
        for bone in bones:
            self._joint_token(bone, joint_tokens)

        joints = [joint_tokens[bone.name] for bone in bones]
        bind_transforms = [scaled_matrix_to_gf(bone.matrix_local, self.mesh_scale) for bone in bones]
        rest_transforms = [self._local_rest_matrix(bone, bone_names, self.mesh_scale) for bone in bones]

        skeleton.CreateJointsAttr(joints)
        skeleton.CreateBindTransformsAttr(bind_transforms)
        skeleton.CreateRestTransformsAttr(rest_transforms)
        skeleton.AddTransformOp().Set(scaled_matrix_to_gf(armature_obj.matrix_world, self.mesh_scale))

    @classmethod
    def _joint_token(cls, bone, joint_tokens):
        """
        build and cache joint path tokens, recursively resolving parent ancestors
        """
        token = joint_tokens.get(bone.name)
        if token is not None:
            return token

        name = sanitize_name(bone.name)
        token = name if bone.parent is None else f"{cls._joint_token(bone.parent, joint_tokens)}/{name}"
        joint_tokens[bone.name] = token
        return token

    @staticmethod
    def _local_rest_matrix(bone, included_bone_names, mesh_scale):
        if bone.parent is None or bone.parent.name not in included_bone_names:
            return scaled_matrix_to_gf(bone.matrix_local, mesh_scale)
        return scaled_matrix_to_gf(bone.parent.matrix_local.inverted() @ bone.matrix_local, mesh_scale)

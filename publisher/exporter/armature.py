from pxr import UsdGeom, UsdSkel, Usd
from publisher.exporter.common import (
    armature_scope_path,
    bone_ancestors,
    find_armature_modifier,
    matrix_to_gf,
    sanitize_name,
)


class SkeletonBindingPlan:
    """
    determine required bones per armature and assign target USD Skeleton prims.
    Bones used exclusively by a variant are isolated into a dedicated Skeleton prim,
    while shared bones remain on the root skeleton.
    """

    def __init__(self, asset_item):
        self.asset_item = asset_item
        self.skeletons = {}
        self.mesh_bindings = {}

        for armature_obj in asset_item.armature_objects.values():
            self._plan_armature(armature_obj)

    def _plan_armature(self, armature_obj):
        root = self.asset_item.variant_root
        skeleton_name = sanitize_name(armature_obj.name)
        root_skeleton_path = f"{armature_scope_path(self.asset_item.name, True)}/{skeleton_name}"

        root_bones = self._bones_for(armature_obj, root.outliner_paths)
        if root_bones:
            self.skeletons[root_skeleton_path] = (armature_obj, root_bones)
            self._bind_meshes(armature_obj, root.outliner_paths, root_skeleton_path, root_bones)

        self._plan_variants(armature_obj, root.variant_sets, root_bones, root_skeleton_path, skeleton_name)

    def _plan_variants(self, armature_obj, variant_sets, inherited_bones, inherited_skeleton_path, skeleton_name):
        for variants in variant_sets.values():
            for variant_name, node in variants.items():
                node_bones = self._bones_for(armature_obj, node.outliner_paths)
                extra_bones = [name for name in node_bones if name not in inherited_bones]

                if extra_bones:
                    combined_names = set(inherited_bones) | set(node_bones)
                    active_bones = [b.name for b in armature_obj.data.bones if b.name in combined_names]
                    active_skeleton_path = (
                        f"{armature_scope_path(self.asset_item.name, True)}/"
                        f"{skeleton_name}_{sanitize_name(variant_name)}"
                    )
                    self.skeletons[active_skeleton_path] = (armature_obj, active_bones)
                else:
                    active_bones, active_skeleton_path = inherited_bones, inherited_skeleton_path

                if active_bones:
                    self._bind_meshes(armature_obj, node.outliner_paths, active_skeleton_path, active_bones)

                self._plan_variants(armature_obj, node.variant_sets, active_bones, active_skeleton_path, skeleton_name)

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
    export static bind-pose skeletons, separating shared and variant-only bones
    """

    def export(self, output_path, asset_item):
        stage = Usd.Stage.CreateNew(output_path)
        if not asset_item.armature_objects:
            return

        plan = SkeletonBindingPlan(asset_item)
        if not plan.skeletons:
            return

        UsdGeom.Scope.Define(stage, armature_scope_path(asset_item.name, True))
        for skeleton_path, (armature_obj, bone_names) in plan.skeletons.items():
            self._write_skeleton(stage, skeleton_path, armature_obj, bone_names)
        return stage
    
    def _write_skeleton(self, stage, skeleton_path, armature_obj, bone_names):
        skeleton = UsdSkel.Skeleton.Define(stage, skeleton_path)
        bones = [armature_obj.data.bones[name] for name in bone_names]

        joint_tokens = {}
        for bone in bones:
            self._joint_token(bone, joint_tokens)

        joints = [joint_tokens[bone.name] for bone in bones]
        bind_transforms = [matrix_to_gf(bone.matrix_local) for bone in bones]
        rest_transforms = [self._local_rest_matrix(bone, bone_names) for bone in bones]

        skeleton.CreateJointsAttr(joints)
        skeleton.CreateBindTransformsAttr(bind_transforms)
        skeleton.CreateRestTransformsAttr(rest_transforms)
        skeleton.AddTransformOp().Set(matrix_to_gf(armature_obj.matrix_world))

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
    def _local_rest_matrix(bone, included_bone_names):
        if bone.parent is None or bone.parent.name not in included_bone_names:
            return matrix_to_gf(bone.matrix_local)
        return matrix_to_gf(bone.parent.matrix_local.inverted() @ bone.matrix_local)

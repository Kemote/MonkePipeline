import os
import math
import bpy

from pxr import Usd, UsdGeom, UsdShade, UsdSkel, Sdf, Gf
from publisher.collector import VARIANT_SEPARATOR


FPS = 30
DEFORM_MODIFIER_TYPES = {"ARMATURE", "CLOTH", "SOFT_BODY", "SURFACE_DEFORM"}
MAX_JOINT_INFLUENCES = 4

LOD_VARIANT_SET = "lod"
LOD_PURPOSES = {
    "render": UsdGeom.Tokens.render,
    "proxy": UsdGeom.Tokens.proxy,
}


def sanitize_name(name):
    sanitized = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
    if sanitized[:1].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def split_variant(name):
    """splits "set{VARIANT_SEPARATOR}variant" into (set_name, variant_name); (None, name) otherwise"""
    parts = name.split(VARIANT_SEPARATOR)
    if len(parts) > 1:
        return parts[0], parts[-1]
    return None, name


def is_lod_set(variant_set_name):
    return variant_set_name.lower() == LOD_VARIANT_SET


def lod_purpose(variant_name):
    return LOD_PURPOSES.get(variant_name.lower(), UsdGeom.Tokens.guide)


def asset_root_path(asset_name):
    return f"/{sanitize_name(asset_name)}"


def geom_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Geom"


def looks_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Looks"


def armature_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Rig"


def mesh_prim_path(asset_name, asset_outliner_path, outliner_path):
    """
    maps a mesh's outliner path (relative to the asset group) onto
    /{asset_name}/Geom/... - a variant collection ("set_VAR_variant") contributes
    no path component, since the variantSet selection already encodes that choice;
    the exception is a lod collection, whose meshes compose under a prim named
    after the lod's purpose (render/proxy/guide) so every lod can coexist
    """
    relative = outliner_path[len(asset_outliner_path):].strip("/")
    parts = []
    for part in relative.split("/"):
        if not part:
            continue
        set_name, variant_name = split_variant(part)
        if set_name is None:
            parts.append(sanitize_name(part))
        elif is_lod_set(set_name):
            parts.append(lod_purpose(variant_name))
    return "/".join([geom_scope_path(asset_name)] + parts)


def base_material_name(material_name):
    """a material named "base{VARIANT_SEPARATOR}variant" belongs to the "base" variant group"""
    return material_name.split(VARIANT_SEPARATOR)[0]


def material_prim_name(material_name):
    """
    "base_VAR_variant" materials become "{base}_{variant}" prims - the separator is
    dropped but both halves are kept, so names stay unique across variant groups
    (unlike keeping just the variant, where wood_VAR_dark and metal_VAR_dark clash)
    """
    set_name, variant_name = split_variant(material_name)
    if set_name is None:
        return sanitize_name(material_name)
    return f"{sanitize_name(set_name)}_{sanitize_name(variant_name)}"


def matrix_to_gf(matrix_world):
    transposed = matrix_world.transposed()
    return Gf.Matrix4d(*[component for row in transposed for component in row])


def bone_ancestors(bone):
    ancestors = []
    current = bone.parent
    while current is not None:
        ancestors.append(current)
        current = current.parent
    return ancestors


def find_armature_modifier(mesh_obj, armature_objects):
    for modifier in mesh_obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object in armature_objects:
            return modifier
    return None


class MeshLayerExporter:
    """
    writes the asset's mesh data layer: hierarchy, topology, uvs and the static
    (bind pose) transform/points - any attribute owned by the animation layer is
    skipped here so the sublayer's timeSamples are free to take effect
    """

    def __init__(self, output_dir, extension):
        self.output_dir = output_dir
        self.extension = extension
        self.binding_exporter = MaterialBindingLayerExporter()

    def export(self, stage: Usd.Stage, asset_item):
        # a SkelRoot is required somewhere above both a Skeleton and the meshes
        # it skins for UsdSkel binding to resolve at all, so the asset root
        # itself becomes one whenever the asset has an armature to bind to
        if asset_item.armature_objects:
            UsdSkel.Root.Define(stage, asset_root_path(asset_item.name))
        else:
            UsdGeom.Xform.Define(stage, asset_root_path(asset_item.name))
        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))

        skeleton_plan = SkeletonBindingPlan(asset_item) if asset_item.armature_objects else None

        root = asset_item.variant_root
        # meshes with no variant belong to the asset itself, so they live directly
        # in this layer and are shared by every variant selection
        self._write_meshes(stage, asset_item, root.outliner_paths, skeleton_plan)
        self._attach_binding_layer(stage, asset_item, root.outliner_paths)

        if root.variant_sets:
            asset_prim = stage.GetPrimAtPath(asset_root_path(asset_item.name))
            variants_dir = os.path.join(self.output_dir, "layers", "mesh_variants")
            self._author_variant_sets(stage, asset_item, asset_prim, root.variant_sets, variants_dir, skeleton_plan)

    def _write_meshes(self, stage, asset_item, outliner_paths, skeleton_plan=None):
        for outliner_path in outliner_paths:
            mesh = asset_item.mesh_objects[outliner_path]
            prim_path = mesh_prim_path(asset_item.name, asset_item.path, outliner_path)
            binding = skeleton_plan.mesh_bindings.get(outliner_path) if skeleton_plan else None
            self._write_mesh(stage, prim_path, mesh, binding)

    def _author_variant_sets(self, stage: Usd.Stage, asset_item, prim: Usd.Prim, variant_sets, variants_dir, skeleton_plan=None):
        """
        authors `variant_sets` onto `prim`. each variant's geometry - its own
        meshes plus any deeper variant sets - is written to a standalone layer laid
        out as <variants_dir>/<set>/<variant>.<ext>; a variant that nests further
        variants recurses into <variants_dir>/<set>/<variant>/, mirroring the
        collection hierarchy on disk. the layer is referenced back into the variant.

        the "lod" set is the exception: lods coexist instead of switching, so no
        variantSet is authored - every lod layer is referenced unconditionally and
        its meshes sit under a prim carrying the matching purpose (render/proxy/
        guide), leaving the choice to the renderer
        """
        os.makedirs(variants_dir, exist_ok=True)
        stage_dir = os.path.dirname(stage.GetRootLayer().realPath)
        variant_sets_api = prim.GetVariantSets()

        for set_name, variants in variant_sets.items():
            set_dir = os.path.join(variants_dir, sanitize_name(set_name))
            os.makedirs(set_dir, exist_ok=True)

            if is_lod_set(set_name):
                for variant_name, node in variants.items():
                    lod_layer_path = self._write_variant_layer(
                        asset_item, set_dir, variant_name, node, skeleton_plan, purpose=lod_purpose(variant_name)
                    )
                    prim.GetReferences().AddReference(os.path.relpath(lod_layer_path, stage_dir))
                continue

            variant_set = variant_sets_api.AddVariantSet(set_name)
            for variant_name, node in variants.items():
                variant_set.AddVariant(variant_name)
                variant_layer_path = self._write_variant_layer(asset_item, set_dir, variant_name, node, skeleton_plan)
                variant_set.SetVariantSelection(variant_name)
                with variant_set.GetVariantEditContext():
                    prim.GetReferences().AddReference(os.path.relpath(variant_layer_path, stage_dir))

            # leave a deterministic default selection rather than the last authored one
            variant_set.SetVariantSelection(next(iter(variants)))

    def _write_variant_layer(self, asset_item, set_dir, variant_name, node, skeleton_plan=None, purpose=None):
        variant_layer_path = os.path.join(set_dir, f"{sanitize_name(variant_name)}.{self.extension}")

        variant_stage = Usd.Stage.CreateNew(variant_layer_path)
        if asset_item.armature_objects:
            UsdSkel.Root.Define(variant_stage, asset_root_path(asset_item.name))
        else:
            UsdGeom.Xform.Define(variant_stage, asset_root_path(asset_item.name))
        UsdGeom.Scope.Define(variant_stage, geom_scope_path(asset_item.name))

        if purpose:
            # mesh_prim_path places this layer's meshes under the purpose prim, so
            # the purpose authored here is inherited by everything in the layer
            purpose_scope = UsdGeom.Scope.Define(
                variant_stage, f"{geom_scope_path(asset_item.name)}/{purpose}"
            )
            purpose_scope.CreatePurposeAttr().Set(purpose)

        self._write_meshes(variant_stage, asset_item, node.outliner_paths, skeleton_plan)
        self._attach_binding_layer(variant_stage, asset_item, node.outliner_paths)

        if node.variant_sets:
            asset_prim = variant_stage.GetPrimAtPath(asset_root_path(asset_item.name))
            nested_dir = os.path.join(set_dir, sanitize_name(variant_name))
            self._author_variant_sets(variant_stage, asset_item, asset_prim, node.variant_sets, nested_dir, skeleton_plan)

        # a defaultPrim lets the parent layer reference this file without naming a prim
        variant_stage.GetRootLayer().defaultPrim = sanitize_name(asset_item.name)
        variant_stage.GetRootLayer().Save()
        return variant_layer_path

    def _attach_binding_layer(self, stage, asset_item, outliner_paths):
        """
        writes the sibling "<layer name>_binding" file holding the material
        bindings for the meshes of this geometry layer, and sublayers it so the
        layer carries its own bindings wherever it is referenced
        """
        if not outliner_paths:
            return
        geo_layer = stage.GetRootLayer()
        binding_layer_path = self.binding_exporter.write_for_layer(geo_layer.realPath, asset_item, outliner_paths)
        # the binding file sits next to its geometry layer, so the relative path is just the name
        geo_layer.subLayerPaths.append(os.path.basename(binding_layer_path))

    def _write_mesh(self, stage, prim_path, mesh_obj, skeleton_binding=None):
        usd_mesh = UsdGeom.Mesh.Define(stage, prim_path)
        mesh_data = mesh_obj.data

        usd_mesh.CreateFaceVertexCountsAttr([len(p.vertices) for p in mesh_data.polygons])
        usd_mesh.CreateFaceVertexIndicesAttr([idx for p in mesh_data.polygons for idx in p.vertices])
        usd_mesh.CreatePointsAttr([Gf.Vec3f(v.co.x, v.co.y, v.co.z) for v in mesh_data.vertices])
        usd_mesh.AddTransformOp().Set(matrix_to_gf(mesh_obj.matrix_world))

        if mesh_data.uv_layers.active:
            uv_attr = UsdGeom.PrimvarsAPI(usd_mesh).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
            )
            uv_attr.Set([Gf.Vec2f(uv.uv.x, uv.uv.y) for uv in mesh_data.uv_layers.active.data])

        if skeleton_binding:
            self._write_skin_binding(usd_mesh, mesh_obj, skeleton_binding)

    @staticmethod
    def _write_skin_binding(usd_mesh, mesh_obj, skeleton_binding):
        """
        authors the UsdSkelBindingAPI data that ties this mesh to its skeleton:
        which Skeleton it deforms with, each vertex's influencing joints/weights
        (its Blender vertex groups, up to MAX_JOINT_INFLUENCES, normalized and
        padded), and the bind-time transform the skinning is relative to
        """
        skeleton_path, bone_names = skeleton_binding
        bone_index = {name: index for index, name in enumerate(bone_names)}

        binding_api = UsdSkel.BindingAPI.Apply(usd_mesh.GetPrim())
        binding_api.CreateSkeletonRel().SetTargets([Sdf.Path(skeleton_path)])

        indices, weights = MeshLayerExporter._per_vertex_weights(mesh_obj, bone_index)
        binding_api.CreateJointIndicesPrimvar(constant=False, elementSize=MAX_JOINT_INFLUENCES).Set(indices)
        binding_api.CreateJointWeightsPrimvar(constant=False, elementSize=MAX_JOINT_INFLUENCES).Set(weights)
        binding_api.CreateGeomBindTransformAttr().Set(matrix_to_gf(mesh_obj.matrix_world))

    @staticmethod
    def _per_vertex_weights(mesh_obj, bone_index):
        indices = []
        weights = []
        for vertex in mesh_obj.data.vertices:
            influences = sorted(
                (
                    (bone_index[mesh_obj.vertex_groups[group.group].name], group.weight)
                    for group in vertex.groups
                    if mesh_obj.vertex_groups[group.group].name in bone_index
                ),
                key=lambda pair: pair[1],
                reverse=True,
            )[:MAX_JOINT_INFLUENCES]

            total_weight = sum(weight for _, weight in influences) or 1.0
            pad = MAX_JOINT_INFLUENCES - len(influences)

            indices.extend([index for index, _ in influences] + [0] * pad)
            weights.extend([weight / total_weight for _, weight in influences] + [0.0] * pad)

        return indices, weights


class MaterialsLayerExporter:
    # TODO: now its takes only bae color from BSDF, we need to get more data from materials,
    # maybe it should be converted to MAterialX

    """
    collects every material used by the asset's meshes under /{asset_name}/Looks -
    including each variant material ("base_VAR_variant"), written as an ordinary
    Material prim named "{base}_{variant}". switching between variant materials is
    done by the binding variantSets authored in the material binding layer, not here
    """

    def export(self, stage, asset_item):
        looks_path = looks_scope_path(asset_item.name)
        UsdGeom.Scope.Define(stage, looks_path)

        for material in asset_item.materials.values():
            self._write_material(stage, f"{looks_path}/{material_prim_name(material.name)}", material)

        for variants in asset_item.material_variants.values():
            for material in variants.values():
                self._write_material(stage, f"{looks_path}/{material_prim_name(material.name)}", material)

    def _write_material(self, stage, material_path, material):
        usd_material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")

        base_color =  self._get_base_color(material)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(base_color[0], base_color[1], base_color[2])
        )

        texture_path = self._find_base_color_texture(material)
        if texture_path:
            self._connect_texture(stage, material_path, shader, texture_path)

        usd_material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    @staticmethod
    def _get_base_color(material):
        rgba = [1.0, 0.0, 0.7]
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    rgba = list(node.inputs[0].default_value)
        return rgba

    @staticmethod
    def _find_base_color_texture(material):
        if not material.use_nodes or not material.node_tree:
            return None
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                return bpy.path.abspath(node.image.filepath)
        return None

    def _connect_texture(self, stage, material_path, shader, texture_path):
        texture_shader = UsdShade.Shader.Define(stage, f"{material_path}/BaseColorTexture")
        texture_shader.CreateIdAttr("UsdUVTexture")
        texture_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_path)
        texture_output = texture_shader.CreateOutput("rgb", Sdf.ValueTypeNames.Color3f)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(texture_output)


class MaterialBindingLayerExporter:
    """
    writes, next to every geometry layer, its "<layer name>_binding" companion:
    `over` prims that bind that layer's meshes to Materials under
    /{asset_name}/Looks. a mesh using a single material gets one whole-mesh
    binding; a mesh whose polygons reference more than one material slot gets a
    face GeomSubset (by polygon.material_index) per material instead.

    a mesh using a variant material ("base_VAR_variant") is not bound directly:
    its binding is authored inside a variantSet (named after the base material) on
    the asset root prim, where each variant rebinds every such mesh/subset to the
    matching "{base}_{variant}" Material prim from the materials layer
    """

    def write_for_layer(self, geo_layer_path, asset_item, outliner_paths):
        base_path, extension = os.path.splitext(geo_layer_path)
        binding_layer_path = f"{base_path}_binding{extension}"

        stage = Usd.Stage.CreateNew(binding_layer_path)
        self.export(stage, asset_item, outliner_paths)
        stage.GetRootLayer().Save()
        return binding_layer_path

    def export(self, stage, asset_item, outliner_paths):
        looks_path = looks_scope_path(asset_item.name)

        # base material name -> paths of the prims (meshes or subsets) whose
        # binding must switch with that material's variant selection
        variant_bindings = {}

        for outliner_path in outliner_paths:
            mesh_obj = asset_item.mesh_objects[outliner_path]
            materials = self._used_materials(mesh_obj)
            if not materials:
                continue

            prim_path = mesh_prim_path(asset_item.name, asset_item.path, outliner_path)
            over_prim = stage.OverridePrim(prim_path)
            binding_api = UsdShade.MaterialBindingAPI.Apply(over_prim)

            if len(materials) == 1:
                _, material = materials[0]
                self._add_binding(over_prim, looks_path, material, variant_bindings)
            else:
                self._bind_subsets(binding_api, mesh_obj, materials, looks_path, variant_bindings)

        self._author_variant_bindings(stage, asset_item, looks_path, variant_bindings)

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

            # the subset is named after the base material so it stays stable while
            # the variant selection swaps which material it is bound to
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

    def _author_variant_bindings(self, stage, asset_item, looks_path, variant_bindings):
        if not variant_bindings:
            return

        root_prim = stage.OverridePrim(asset_root_path(asset_item.name))
        for base_name, prim_paths in variant_bindings.items():
            variants = asset_item.material_variants.get(base_name)
            if not variants:
                continue

            variant_set = root_prim.GetVariantSets().AddVariantSet(base_name)
            for variant_name, material in variants.items():
                variant_set.AddVariant(variant_name)
                variant_set.SetVariantSelection(variant_name)
                # prim_paths are descendants of the root prim, so the bindings
                # authored here land inside this variant instead of on the prims
                with variant_set.GetVariantEditContext():
                    for prim_path in prim_paths:
                        self._bind(stage.GetPrimAtPath(prim_path), looks_path, material)

            # leave a deterministic default selection rather than the last authored one
            variant_set.SetVariantSelection(next(iter(variants)))

    @staticmethod
    def _bind(prim, looks_path, material):
        # Bind() needs a resolvable Material prim, but this layer is written
        # standalone with no sublayer that defines /{asset_name}/Looks, so author
        # the "material:binding" relationship directly instead
        material_path = f"{looks_path}/{material_prim_name(material.name)}"
        prim.CreateRelationship("material:binding", custom=False).SetTargets([Sdf.Path(material_path)])


class SkeletonBindingPlan:
    """
    figures out, per armature, which bones are actually needed and which
    Skeleton prim each mesh should bind to.

    a bone that's only ever weight-painted on meshes belonging to one variant
    (e.g. an extra bone driving a variant-only prop) has no business showing up
    in the skeleton when a different variant is selected - so instead of one
    skeleton with every bone always present, this walks the asset's variant
    tree the same way MeshLayerExporter does: the root skeleton only gets
    bones used by non-variant meshes, and a variant only gets its own
    additional Skeleton prim (self-contained, full ancestor chain included)
    if its meshes use bones the root skeleton doesn't already have. meshes
    that only need root bones keep binding to the root skeleton.

    skeletons: {skeleton_path: (armature_obj, [bone names in armature order])}
    mesh_bindings: {outliner_path: (skeleton_path, [bone names in armature order])}
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
        root_skeleton_path = f"{armature_scope_path(self.asset_item.name)}/{skeleton_name}"

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
                        f"{armature_scope_path(self.asset_item.name)}/"
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
        """ancestor-expanded list of bone names used by these meshes, kept in the armature's own bone order"""
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
    writes the asset's armature(s) as UsdSkel Skeletons under /{asset_name}/Rig,
    using a SkeletonBindingPlan to decide which bones belong on the shared root
    skeleton versus a dedicated per-variant companion skeleton. only the static
    bind-pose joint hierarchy is authored here; animating the skeleton's joints
    is left to the animation layer, kept separate for the same reason mesh
    statics and mesh animation are split
    """

    def export(self, stage, asset_item):
        if not asset_item.armature_objects:
            return

        plan = SkeletonBindingPlan(asset_item)
        if not plan.skeletons:
            return

        UsdGeom.Scope.Define(stage, armature_scope_path(asset_item.name))
        for skeleton_path, (armature_obj, bone_names) in plan.skeletons.items():
            self._write_skeleton(stage, skeleton_path, armature_obj, bone_names)

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
        builds this bone's "Parent/.../bone" joint path token, memoized in
        joint_tokens - bones normally iterate parents-before-children, but a
        parent's token is built on demand here too in case that ever isn't true.
        SkeletonBindingPlan always includes a bone's full ancestor chain
        alongside it, so the parent is guaranteed to be resolvable here
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


class UsdExporter:
    def __init__(self, settings):

        self.output_dir = settings["filepath"]
        self.extension = settings["extension"]
        
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

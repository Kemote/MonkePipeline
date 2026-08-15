import os

from pxr import Usd, UsdGeom, UsdSkel, Sdf, Gf
from publisher import collector
# from publisher.proxy_generator.proxy_generator import ProxyGenerator
from publisher.exporter.armature import SkeletonBindingPlan
from publisher.exporter.common import (
    MAX_JOINT_INFLUENCES,
    asset_root_path,
    geom_scope_path,
    is_lod_set,
    lod_purpose,
    matrix_to_gf,
    mesh_prim_path,
    sanitize_name,
)
from publisher.exporter.material_binding import MaterialBindingLayerExporter


class MeshLayerExporter:
    """
    writes the asset's mesh data layer: hierarchy, topology, uvs and the static
    (bind pose) transform/points - any attribute owned by the animation layer is
    skipped here so the sublayer's timeSamples are free to take effect
    """

    def __init__(self, variants_dir, extension):
        self.variants_dir = variants_dir
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

        root : collector.VariantNode = asset_item.variant_root
        # meshes with no variant belong to the asset itself, so they live directly
        # in this layer and are shared by every variant selection
        self._write_meshes(stage, asset_item, root.outliner_paths, skeleton_plan)
        self._attach_binding_layer(stage, asset_item, root.outliner_paths)

        if root.variant_sets:
            asset_prim = stage.GetPrimAtPath(asset_root_path(asset_item.name))
            # variants_dir = os.path.join(self.output_dir, "layers", "mesh_variants")
            self._author_variant_sets(stage, asset_item, asset_prim, root.variant_sets, self.variants_dir, skeleton_plan)

    def _write_meshes(self, stage, asset_item, outliner_paths, skeleton_plan=None):
        for outliner_path in outliner_paths:
            mesh = asset_item.mesh_objects[outliner_path]
            prim_path = mesh_prim_path(asset_item.name, asset_item.path, outliner_path)
            binding = skeleton_plan.mesh_bindings.get(outliner_path) if skeleton_plan else None
            self._write_mesh(stage, prim_path, mesh, binding)

    def _author_variant_sets(self, 
                             stage: Usd.Stage, 
                             asset_item: collector.CollectedAssetItem, 
                             prim: Usd.Prim, 
                             variant_sets, 
                             variants_dir, 
                             skeleton_plan=None):
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

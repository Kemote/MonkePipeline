import os
import math
import bpy

from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf
from collector import VARIANT_SEPARATOR


FPS = 30
DEFORM_MODIFIER_TYPES = {"ARMATURE", "CLOTH", "SOFT_BODY", "SURFACE_DEFORM"}


def sanitize_name(name):
    sanitized = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
    if sanitized[:1].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def asset_root_path(asset_name):
    return f"/{sanitize_name(asset_name)}"


def geom_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Geom"


def looks_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Looks"


def mesh_prim_path(asset_name, asset_outliner_path, outliner_path):
    """maps a mesh's outliner path (relative to the asset group) onto /{asset_name}/Geom/..."""
    relative = outliner_path[len(asset_outliner_path):].strip("/")
    parts = [sanitize_name(part) for part in relative.split("/") if part]
    return "/".join([geom_scope_path(asset_name)] + parts)


def base_material_name(material_name):
    """a material named "base{VARIANT_SEPARATOR}variant" composes into the base Material prim"""
    return material_name.split(VARIANT_SEPARATOR)[0]


def matrix_to_gf(matrix_world):
    transposed = matrix_world.transposed()
    return Gf.Matrix4d(*[component for row in transposed for component in row])


class AnimationInspector:
    """
    classifies an object's animation so the mesh layer and the animation layer
    never author competing opinions for the same attribute (a stronger root layer
    opinion would otherwise permanently shadow the weaker sublayer's timeSamples)
    """

    @staticmethod
    def is_transform_animated(mesh_obj):
        action = mesh_obj.animation_data and mesh_obj.animation_data.action
        if not action:
            return False
        return any(
            fcurve.data_path.startswith(("location", "rotation_euler", "rotation_quaternion", "scale"))
            for fcurve in action.fcurves
        )

    @staticmethod
    def is_deformed(mesh_obj):
        if mesh_obj.data.shape_keys and mesh_obj.data.shape_keys.animation_data:
            return True
        return any(modifier.type in DEFORM_MODIFIER_TYPES for modifier in mesh_obj.modifiers)


class MeshLayerExporter:
    """
    writes the asset's mesh data layer: hierarchy, topology, uvs and the static
    (bind pose) transform/points - any attribute owned by the animation layer is
    skipped here so the sublayer's timeSamples are free to take effect
    """

    def __init__(self, output_dir, extension):
        self.output_dir = output_dir
        self.extension = extension

    def export(self, stage: Usd.Stage, asset_item):
        UsdGeom.Xform.Define(stage, asset_root_path(asset_item.name))
        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))

        root = asset_item.variant_root
        # meshes with no variant belong to the asset itself, so they live directly
        # in this layer and are shared by every variant selection
        self._write_meshes(stage, asset_item, root.outliner_paths)

        if root.variant_sets:
            asset_prim = stage.GetPrimAtPath(asset_root_path(asset_item.name))
            variants_dir = os.path.join(self.output_dir, "layers", "mesh_variants")
            self._author_variant_sets(stage, asset_item, asset_prim, root.variant_sets, variants_dir)

    def _write_meshes(self, stage, asset_item, outliner_paths):
        for outliner_path in outliner_paths:
            mesh = asset_item.mesh_objects[outliner_path]
            prim_path = mesh_prim_path(asset_item.name, asset_item.usd_like_path, outliner_path)
            self._write_mesh(stage, prim_path, mesh)

    def _author_variant_sets(self, stage: Usd.Stage, asset_item, prim: Usd.Prim, variant_sets, variants_dir):
        """
        authors `variant_sets` onto `prim`. each variant's geometry - its own
        meshes plus any deeper variant sets - is written to a standalone layer laid
        out as <variants_dir>/<set>/<variant>.<ext>; a variant that nests further
        variants recurses into <variants_dir>/<set>/<variant>/, mirroring the
        collection hierarchy on disk. the layer is referenced back into the variant
        """
        root_layer = stage.GetRootLayer()
        os.makedirs(variants_dir, exist_ok=True)
        stage_dir = os.path.dirname(root_layer.realPath)
        variant_sets_api = prim.GetVariantSets()
        
        for set_name, variants in variant_sets.items():
            set_dir = os.path.join(variants_dir, sanitize_name(set_name))
            os.makedirs(set_dir, exist_ok=True)
            # if variant set name is "lod" itt should be treatend as pupropse insteed regular variant set
            if set_name.lower() != "lod":
                variant_set = variant_sets_api.AddVariantSet(set_name)
                for variant_name, node in variants.items():
                    variant_set.AddVariant(variant_name)
                    variant_layer_path = self._write_variant_layer(asset_item, set_dir, variant_name, node)
                    variant_set.SetVariantSelection(variant_name)
                    with variant_set.GetVariantEditContext():
                        reference_path = os.path.relpath(variant_layer_path, stage_dir)
                        prim.GetReferences().AddReference(reference_path)
                # leave a deterministic default selection rather than the last authored one
                variant_set.SetVariantSelection(next(iter(variants)))

            # we treat lod set differently, it should be set as a set of prims with purpose
            else:
                for variant_name, node in variants.items():
                    lod_layer_path = self._write_variant_layer(asset_item, set_dir, variant_name, node)
                    geom_path = geom_scope_path(asset_item.name)
                    lod_prim = stage.DefinePrim(f"{geom_path}/{variant_name}", "Scope")
                    
                    reference_path = os.path.relpath(lod_layer_path, stage_dir)
                    lod_prim.GetReferences().AddReference(reference_path)

                    purpose_attr = lod_prim.GetAttribute("purpose")
                    if variant_name.lower() in ["render", "high"]:
                        purpose_attr.Set("render")
                    elif variant_name.lower() in ["proxy", "low"]:
                        purpose_attr.Set("proxy")
                    else:
                        purpose_attr.Set("guide")

    def _write_variant_layer(self, asset_item, set_dir, variant_name, node):
        variant_layer_path = os.path.join(set_dir, f"{sanitize_name(variant_name)}.{self.extension}")

        variant_stage = Usd.Stage.CreateNew(variant_layer_path)
        UsdGeom.Xform.Define(variant_stage, asset_root_path(asset_item.name))
        UsdGeom.Scope.Define(variant_stage, geom_scope_path(asset_item.name))

        self._write_meshes(variant_stage, asset_item, node.outliner_paths)

        if node.variant_sets:
            asset_prim = variant_stage.GetPrimAtPath(asset_root_path(asset_item.name))
            nested_dir = os.path.join(set_dir, sanitize_name(variant_name))
            self._author_variant_sets(variant_stage, asset_item, asset_prim, node.variant_sets, nested_dir)

        # a defaultPrim lets the parent layer reference this file without naming a prim
        variant_stage.GetRootLayer().defaultPrim = sanitize_name(asset_item.name)
        variant_stage.GetRootLayer().Save()
        return variant_layer_path

    def _write_mesh(self, stage, prim_path, mesh_obj):
        usd_mesh = UsdGeom.Mesh.Define(stage, prim_path)
        mesh_data = mesh_obj.data

        usd_mesh.CreateFaceVertexCountsAttr([len(p.vertices) for p in mesh_data.polygons])
        usd_mesh.CreateFaceVertexIndicesAttr([idx for p in mesh_data.polygons for idx in p.vertices])

        if not AnimationInspector.is_deformed(mesh_obj):
            usd_mesh.CreatePointsAttr([Gf.Vec3f(v.co.x, v.co.y, v.co.z) for v in mesh_data.vertices])

        if mesh_data.uv_layers.active:
            uv_attr = UsdGeom.PrimvarsAPI(usd_mesh).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
            )
            uv_attr.Set([Gf.Vec2f(uv.uv.x, uv.uv.y) for uv in mesh_data.uv_layers.active.data])

        if not AnimationInspector.is_transform_animated(mesh_obj):
            usd_mesh.AddTransformOp().Set(matrix_to_gf(mesh_obj.matrix_world))


class MaterialsLayerExporter:
    # TODO: now its takes only bae color from BSDF, we need to get more data from materials,
    # maybe it should be converted to MAterialSX

    """
    collects every material used by the asset's meshes under /{asset_name}/Looks -
    including each variant material ("base_VAR_variant"), written as an ordinary
    Material prim under its full name. switching between variant materials is done
    by the binding variantSets authored in the material binding layer, not here
    """

    def export(self, stage, asset_item):
        looks_path = looks_scope_path(asset_item.name)
        UsdGeom.Scope.Define(stage, looks_path)

        for material in asset_item.materials.values():
            self._write_material(stage, f"{looks_path}/{sanitize_name(material.name)}", material)

        for variants in asset_item.material_variants.values():
            for material in variants.values():
                self._write_material(stage, f"{looks_path}/{sanitize_name(material.name)}", material)

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
    authors `over` prims, scoped under /{asset_name}/Geom, that bind each mesh to
    its material(s) under /{asset_name}/Looks. a mesh using a single material gets
    one whole-mesh binding; a mesh whose polygons reference more than one material
    slot gets a face GeomSubset (by polygon.material_index) per material instead.

    a mesh using a variant material ("base_VAR_variant") is not bound directly:
    its binding is authored inside a variantSet (named after the base material) on
    the asset root prim, where each variant rebinds every such mesh/subset to the
    matching "base_VAR_*" Material prim from the materials layer
    """

    def export(self, stage, asset_item):
        looks_path = looks_scope_path(asset_item.name)
        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))

        # base material name -> paths of the prims (meshes or subsets) whose
        # binding must switch with that material's variant selection
        variant_bindings = {}

        for outliner_path, mesh_obj in asset_item.mesh_objects.items():
            materials = self._used_materials(mesh_obj)
            if not materials:
                continue

            prim_path = mesh_prim_path(asset_item.name, asset_item.usd_like_path, outliner_path)
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
        material_path = f"{looks_path}/{sanitize_name(material.name)}"
        prim.CreateRelationship("material:binding", custom=False).SetTargets([Sdf.Path(material_path)])


# class AnimationLayerExporter:
#     """
#     authors `over` prims, scoped under /{asset_name}/Geom, carrying timeSamples:
#     decomposed translate/rotate/scale ops for objects animated only by their
#     transform, and time-sampled `points` for meshes that are actually deformed
#     (shape keys, armature, cloth, etc.)
#     """

#     def export(self, stage, asset_item):
#         scene = bpy.context.scene
#         depsgraph = bpy.context.evaluated_depsgraph_get()

#         UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))

#         deformed = {}
#         transform_animated = {}
#         for outliner_path, mesh_obj in asset_item.mesh_objects.items():
#             prim_path = mesh_prim_path(asset_item.name, asset_item.usd_like_path, outliner_path)
#             if AnimationInspector.is_deformed(mesh_obj):
#                 deformed[prim_path] = mesh_obj
#             if AnimationInspector.is_transform_animated(mesh_obj):
#                 transform_animated[prim_path] = mesh_obj

#         if not deformed and not transform_animated:
#             return

#         points_attrs = {
#             prim_path: UsdGeom.Mesh(stage.OverridePrim(prim_path)).CreatePointsAttr()
#             for prim_path in deformed
#         }
#         xform_ops = {prim_path: self._add_transform_ops(stage, prim_path) for prim_path in transform_animated}

#         original_frame = scene.frame_current
#         try:
#             for frame in range(scene.frame_start, scene.frame_end + 1):
#                 scene.frame_set(frame)
#                 depsgraph.update()
#                 time_code = Usd.TimeCode(frame)

#                 for path, mesh_obj in deformed.items():
#                     self._sample_points(mesh_obj, depsgraph, points_attrs[path], time_code)

#                 for path, mesh_obj in transform_animated.items():
#                     self._sample_transform(mesh_obj, xform_ops[path], time_code)
#         finally:
#             scene.frame_set(original_frame)

#         stage.SetStartTimeCode(scene.frame_start)
#         stage.SetEndTimeCode(scene.frame_end)

#     def _add_transform_ops(self, stage, prim_path):
#         over_xform = UsdGeom.Xformable(stage.OverridePrim(prim_path))
#         return over_xform.AddTranslateOp(), over_xform.AddRotateXYZOp(), over_xform.AddScaleOp()

#     @staticmethod
#     def _sample_points(mesh_obj, depsgraph, points_attr, time_code):
#         evaluated_obj = mesh_obj.evaluated_get(depsgraph)
#         evaluated_mesh = evaluated_obj.to_mesh()
#         points_attr.Set([Gf.Vec3f(v.co.x, v.co.y, v.co.z) for v in evaluated_mesh.vertices], time_code)
#         evaluated_obj.to_mesh_clear()

#     @staticmethod
#     def _sample_transform(mesh_obj, xform_ops, time_code):
#         translate_op, rotate_op, scale_op = xform_ops
#         translation, rotation, scale = mesh_obj.matrix_world.decompose()
#         euler = rotation.to_euler("XYZ")

#         translate_op.Set(Gf.Vec3d(translation.x, translation.y, translation.z), time_code)
#         rotate_op.Set(Gf.Vec3f(math.degrees(euler.x), math.degrees(euler.y), math.degrees(euler.z)), time_code)
#         scale_op.Set(Gf.Vec3f(scale.x, scale.y, scale.z), time_code)


class UsdExporter:
    def __init__(self, output_dir, extension="usda"):
        self.output_dir = output_dir
        self.extension = (extension or self.DEFAULT_EXTENSION).lstrip(".")
        self.mesh_exporter = MeshLayerExporter(self.output_dir, self.extension)
        self.materials_exporter = MaterialsLayerExporter()
        self.material_binding_exporter = MaterialBindingLayerExporter()
        # self.animation_exporter = AnimationLayerExporter()

    def export(self, asset_item):
        asset_name = asset_item.name
        layers_dir = os.path.join(self.output_dir, "layers")
        os.makedirs(layers_dir, exist_ok=True)

        mesh_path = os.path.join(layers_dir, f"{asset_name}_geo.{self.extension}")
        materials_path = os.path.join(layers_dir, f"{asset_name}_materials.{self.extension}")
        binding_path = os.path.join(layers_dir, f"{asset_name}_material_binding.{self.extension}")
        animations_path = os.path.join(layers_dir, f"{asset_name}_animations.{self.extension}")
        main_path = os.path.join(self.output_dir, f"{asset_name}.{self.extension}")

        self._write_layer(mesh_path, self.mesh_exporter, asset_item)
        self._write_layer(materials_path, self.materials_exporter, asset_item)
        self._write_layer(binding_path, self.material_binding_exporter, asset_item)
        # self._write_layer(animations_path, self.animation_exporter, asset_item)

        # the main file carries no content of its own, only composition arcs to the
        # layer files above, so it stays a thin, human-readable entry point for the asset
        main_stage = Usd.Stage.CreateNew(main_path)
        self._set_fps(main_stage)
        self._set_metadata(main_stage)

        main_layer = main_stage.GetRootLayer()
        # strongest first: animation overrides win over bindings, materials, then base mesh data
        for layer_path in (animations_path, binding_path, materials_path, mesh_path):
            main_layer.subLayerPaths.append(os.path.relpath(layer_path, self.output_dir))
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

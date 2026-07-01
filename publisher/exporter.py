import os
import math

import bpy

from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf


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

    def export(self, stage: Usd.Stage, asset_item):
        UsdGeom.Xform.Define(stage, asset_root_path(asset_item.name))
        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))
        base_prim_path = mesh_prim_path(asset_item.name, asset_item.outliner_path, outliner_path)

        # maybe spp should ask user what to do in case booth normal and version data exists? Or add default name
        if not asset_item.variants:
            for outliner_path in asset_item.base_objects:
                mesh = asset_item.mesh_objects[outliner_path]
                self._write_mesh(stage, base_prim_path, mesh)

        else:
            base_prim = stage.GetPrimAtPath(base_prim_path)
            if not base_prim_path:
                base_prim = stage.DefinePrim(base_prim_path)

            variant_sets = base_prim.GetVariantSets()
            for variants_set_name, variants_dict in asset_item.variants.items():
                variant_set = variant_sets.AddVariantSet(variants_set_name)
                for variant_name, outliner_paths in variants_dict.items():
                    variant_set.AddVariant(variant_name)

                    #TODO: wyeksportuj wszystko do osobnych layerow i dodaj je jako referencje dla poszczegolnych variantow
                    # CLOUDE: here it should create new layer 




        # TRZEBA TRO INACZEJ ZROBIC, MOZNA BY ZROBIA TAK ABY W RAZIE ZAISTNIENIA VARIANTOW AUTOMATYCZNIE NAZYWAL TEN VARIANT KTORY JEST PUYSTY?

        # if not asset_item.has_variants():
        #     for outliner_path in asset_item.itter_base_objects():
        #         mesh = asset_item.mesh_objects[outliner_path]
        #         self._write_mesh(stage, base_prim_path, mesh)

        # else
        #     base_prim = stage.GetPrimAtPath(base_prim_path)
        #     if not base_prim_path:
        #         base_prim = stage.DefinePrim(base_prim_path)

        #     variant_sets = base_prim.GetVariantSets()
        #     for variant_set_name, variant_name, object_list in asset_item.itter_variants():
        #         variant_sets.AddVariantSet(variant_set_name)



        # for variant_set_name, variant_name, variant_outlinier_paths in asset_item.itter_mesh_objects():
        #     prim_path = mesh_prim_path(asset_item.name, asset_item.outliner_path, outliner_path)
            
        #     if not variant_name:
        #         for outliner_path, mesh_obj in asset_item.mesh_objects.items():
        #             self._write_mesh(stage, prim_path, mesh_obj)
            
        #     else: 
        #          for outliner_path in variant_outlinier_paths:
        #              mesh_obj = asset_item.mesh_objects[outliner_path]
        #              self._write_mesh(stage, prim_path, mesh_obj, variant_name)


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
    """collects every material used by the asset's meshes under /{asset_name}/Looks"""

    def export(self, stage, asset_item):
        looks_path = looks_scope_path(asset_item.name)
        UsdGeom.Scope.Define(stage, looks_path)
        written = set()

        for mesh_obj in asset_item.mesh_objects.values():
            for slot in mesh_obj.material_slots:
                material = slot.material
                if not material or material.name in written:
                    continue
                written.add(material.name)
                self._write_material(stage, looks_path, material)

    def _write_material(self, stage, looks_path, material):
        material_path = f"{looks_path}/{sanitize_name(material.name)}"
        usd_material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")

        base_color = material.diffuse_color
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(base_color[0], base_color[1], base_color[2])
        )

        texture_path = self._find_base_color_texture(material)
        if texture_path:
            self._connect_texture(stage, material_path, shader, texture_path)

        usd_material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

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
    slot gets a face GeomSubset (by polygon.material_index) per material instead
    """

    def export(self, stage, asset_item):
        looks_path = looks_scope_path(asset_item.name)
        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))

        for outliner_path, mesh_obj in asset_item.mesh_objects.items():
            materials = self._used_materials(mesh_obj)
            if not materials:
                continue

            prim_path = mesh_prim_path(asset_item.name, asset_item.outliner_path, outliner_path)
            over_prim = stage.OverridePrim(prim_path)
            binding_api = UsdShade.MaterialBindingAPI.Apply(over_prim)

            if len(materials) == 1:
                _, material = materials[0]
                self._bind(over_prim, looks_path, material)
            else:
                self._bind_subsets(binding_api, mesh_obj, materials, looks_path)

    @staticmethod
    def _used_materials(mesh_obj):
        used_indices = sorted({polygon.material_index for polygon in mesh_obj.data.polygons})
        materials = []
        for index in used_indices:
            if index < len(mesh_obj.material_slots) and mesh_obj.material_slots[index].material:
                materials.append((index, mesh_obj.material_slots[index].material))
        return materials

    def _bind_subsets(self, binding_api, mesh_obj, materials, looks_path):
        for material_index, material in materials:
            face_indices = [
                i for i, polygon in enumerate(mesh_obj.data.polygons)
                if polygon.material_index == material_index
            ]
            if not face_indices:
                continue

            subset = binding_api.CreateMaterialBindSubset(
                sanitize_name(material.name), face_indices, elementType="face"
            )
            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim())
            self._bind(subset.GetPrim(), looks_path, material)

        binding_api.SetMaterialBindSubsetsFamilyType(UsdGeom.Tokens.partition)

    @staticmethod
    def _bind(prim, looks_path, material):
        # Bind() needs a resolvable Material prim, but this layer is written
        # standalone with no sublayer that defines /{asset_name}/Looks, so author
        # the "material:binding" relationship directly instead
        material_path = f"{looks_path}/{sanitize_name(material.name)}"
        prim.CreateRelationship("material:binding", custom=False).SetTargets([Sdf.Path(material_path)])


class AnimationLayerExporter:
    """
    authors `over` prims, scoped under /{asset_name}/Geom, carrying timeSamples:
    decomposed translate/rotate/scale ops for objects animated only by their
    transform, and time-sampled `points` for meshes that are actually deformed
    (shape keys, armature, cloth, etc.)
    """

    def export(self, stage, asset_item):
        scene = bpy.context.scene
        depsgraph = bpy.context.evaluated_depsgraph_get()

        UsdGeom.Scope.Define(stage, geom_scope_path(asset_item.name))

        deformed = {}
        transform_animated = {}
        for outliner_path, mesh_obj in asset_item.mesh_objects.items():
            prim_path = mesh_prim_path(asset_item.name, asset_item.outliner_path, outliner_path)
            if AnimationInspector.is_deformed(mesh_obj):
                deformed[prim_path] = mesh_obj
            if AnimationInspector.is_transform_animated(mesh_obj):
                transform_animated[prim_path] = mesh_obj

        if not deformed and not transform_animated:
            return

        points_attrs = {
            prim_path: UsdGeom.Mesh(stage.OverridePrim(prim_path)).CreatePointsAttr()
            for prim_path in deformed
        }
        xform_ops = {prim_path: self._add_transform_ops(stage, prim_path) for prim_path in transform_animated}

        original_frame = scene.frame_current
        try:
            for frame in range(scene.frame_start, scene.frame_end + 1):
                scene.frame_set(frame)
                depsgraph.update()
                time_code = Usd.TimeCode(frame)

                for path, mesh_obj in deformed.items():
                    self._sample_points(mesh_obj, depsgraph, points_attrs[path], time_code)

                for path, mesh_obj in transform_animated.items():
                    self._sample_transform(mesh_obj, xform_ops[path], time_code)
        finally:
            scene.frame_set(original_frame)

        stage.SetStartTimeCode(scene.frame_start)
        stage.SetEndTimeCode(scene.frame_end)

    def _add_transform_ops(self, stage, prim_path):
        over_xform = UsdGeom.Xformable(stage.OverridePrim(prim_path))
        return over_xform.AddTranslateOp(), over_xform.AddRotateXYZOp(), over_xform.AddScaleOp()

    @staticmethod
    def _sample_points(mesh_obj, depsgraph, points_attr, time_code):
        evaluated_obj = mesh_obj.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_obj.to_mesh()
        points_attr.Set([Gf.Vec3f(v.co.x, v.co.y, v.co.z) for v in evaluated_mesh.vertices], time_code)
        evaluated_obj.to_mesh_clear()

    @staticmethod
    def _sample_transform(mesh_obj, xform_ops, time_code):
        translate_op, rotate_op, scale_op = xform_ops
        translation, rotation, scale = mesh_obj.matrix_world.decompose()
        euler = rotation.to_euler("XYZ")

        translate_op.Set(Gf.Vec3d(translation.x, translation.y, translation.z), time_code)
        rotate_op.Set(Gf.Vec3f(math.degrees(euler.x), math.degrees(euler.y), math.degrees(euler.z)), time_code)
        scale_op.Set(Gf.Vec3f(scale.x, scale.y, scale.z), time_code)


class UsdExporter:
    def __init__(self, output_dir, extension="usda"):
        self.output_dir = output_dir
        self.extension = (extension or self.DEFAULT_EXTENSION).lstrip(".")
        self.mesh_exporter = MeshLayerExporter()
        self.materials_exporter = MaterialsLayerExporter()
        self.material_binding_exporter = MaterialBindingLayerExporter()
        self.animation_exporter = AnimationLayerExporter()

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
        self._write_layer(animations_path, self.animation_exporter, asset_item)

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

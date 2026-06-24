import os
import bpy
from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf


class UsdExporter:
    def __init__(self):
        pass

    def export(self, asset_item, extension):
        """
        writes one USD file per CollectedAssetItem, mirroring each mesh's
        outliner_path (eg /Scene/Assets/AssetName/SomeMesh) as its USD prim path
        """
        file_path = self._build_file_path(asset_item.name, extension)
        stage = Usd.Stage.CreateNew(file_path)
        self._set_metadata(stage)

        for outliner_path, mesh_obj in asset_item.mesh_objects.items():
            self._write_mesh(stage, outliner_path, mesh_obj)

        stage.GetRootLayer().Save()

        return file_path

    def _build_file_path(self, asset_name, extension):
        # TODO: ignore for now in next stpes it should resolve aoutput folder based on item type, it should based on somekind of yaml file
        output_dir = "./"
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, f"{asset_name}.{extension}")

    @staticmethod
    def _sanitize_name(name):
        sanitized = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
        if sanitized[:1].isdigit():
            sanitized = f"_{sanitized}"
        return sanitized

    def _set_metadata(self, stage):
        root_layer = stage.GetRootLayer()
        layer_data = root_layer.customLayerData
        layer_data["userName"] = os.environ.get("MONKENAME", "unknown")
        root_layer.customLayerData = layer_data

    def _write_mesh(self, stage, prim_path, mesh_obj):
        usd_mesh = UsdGeom.Mesh.Define(stage, prim_path)
        mesh_data = mesh_obj.data

        usd_mesh.CreatePointsAttr([Gf.Vec3f(v.co.x, v.co.y, v.co.z) for v in mesh_data.vertices])
        usd_mesh.CreateFaceVertexCountsAttr([len(p.vertices) for p in mesh_data.polygons])
        usd_mesh.CreateFaceVertexIndicesAttr([idx for p in mesh_data.polygons for idx in p.vertices])

        if mesh_data.uv_layers.active:
            uv_attr = UsdGeom.PrimvarsAPI(usd_mesh).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
            )
            uv_attr.Set([Gf.Vec2f(uv.uv.x, uv.uv.y) for uv in mesh_data.uv_layers.active.data])

        self._set_transform(usd_mesh, mesh_obj.matrix_world)
        self._write_materials(stage, usd_mesh, prim_path, mesh_obj)

    def _set_transform(self, usd_mesh, matrix_world):
        transposed = matrix_world.transposed()
        usd_matrix = Gf.Matrix4d(*[component for row in transposed for component in row])
        usd_mesh.AddTransformOp().Set(usd_matrix)

    def _write_materials(self, stage, usd_mesh, prim_path, mesh_obj):
        for slot in mesh_obj.material_slots:
            material = slot.material
            if not material:
                continue

            material_path = f"{prim_path}/{self._sanitize_name(material.name)}_mat"
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
            UsdShade.MaterialBindingAPI(usd_mesh).Bind(usd_material)

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

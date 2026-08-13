import bpy

from publisher.collector import VARIANT_SEPARATOR
from publisher import collector


PROXY_POST_FIX = "_&&_proxy"


class ProxyGenerator:
    def __init__(self, asset_item: collector.CollectedAssetItem , decimate_ratio=0.025):
        self.asset_item = asset_item
        self.mesh_objects = asset_item.mesh_objects
        self.decimate_ratio = decimate_ratio
        self.proxy_collections = []
        self.proxy_meshes = []

    def add_proxy(self):
        for var_set_name, var_dict in self.asset_item.variant_root.variant_sets.items():
            if var_set_name == "lod":
                render_node: collector.VariantNode = var_dict.get("render")
                if not render_node:
                    raise KeyError("Cannot find 'render' group in 'lod' variant collection")
                # create proxy variant node
                proxy_node = collector.VariantNode()
                var_dict["proxy"] = proxy_node
                for outliner_path in render_node.outliner_paths:
                    self._add_proxy_mesh(outliner_path, proxy_node)

                self._add_subvariants(render_node.variant_sets, proxy_node)

    def _add_subvariants(self, variant_sets_dict, proxy_node: collector.VariantNode):
        for variant_set_name, variant_dict in variant_sets_dict.items():
            for variant_name, variant_node in variant_dict.items():
                proxy_variant_node = proxy_node.add_variant(variant_set_name, variant_name)
                for outliner_path in variant_node.outliner_paths:
                    self._add_proxy_mesh(outliner_path, proxy_variant_node)
                self._add_subvariants(variant_node.variant_sets, proxy_variant_node)

    
    def generate_proxy(self, source_mesh, source_path):
        """
        method which generate lod proxy mesh and put it to the appropriate collection
        return mesh object and it's scene path
        """
        target_path = source_path.replace(f"{collector.VARIANT_SEPARATOR}render", 
                                          f"{collector.VARIANT_SEPARATOR}proxy")
        target_collection_parts = target_path.split("/")
        target_collection_path = "/".join(target_collection_parts[:-1]) + PROXY_POST_FIX
        target_collection = self.get_or_create_collection_path(target_collection_path)
        mesh = self._create_mesh_copy(source_mesh, target_collection, self.decimate_ratio)
        scene_path = f"{target_collection_path}/{mesh.name}"
        self.proxy_meshes.append(mesh)
        self.proxy_collections.append(scene_path)
        return mesh, scene_path

    def _add_proxy_mesh(self, source_path, proxy_node: collector.VariantNode):
        src_mesh = self.mesh_objects[source_path]
        proxy_mesh, proxy_scene_path = self.generate_proxy(src_mesh, source_path)
        # add proxy paths to item
        self.mesh_objects[proxy_scene_path] = proxy_mesh
        proxy_node.outliner_paths.append(proxy_scene_path)

    def _create_mesh_copy(self, mesh, target_collection, decimate_ratio):
        proxy_name = f"{mesh.name}{PROXY_POST_FIX}"
        new_mesh = mesh.copy()
        new_mesh.data = mesh.data.copy()
        new_mesh.name = proxy_name
        target_collection.objects.link(new_mesh)
        self.reduce_polycount(new_mesh, decimate_ratio)
        return new_mesh

    @staticmethod
    def reduce_polycount(mesh, decimate_ratio):
        decimate_mod = mesh.modifiers.new("proxy_generator_decimate", "DECIMATE")
        decimate_mod.ratio = decimate_ratio
        with bpy.context.temp_override(active_object=mesh, selected_editable_objects=[mesh]):
            bpy.context.view_layer.objects.active = mesh
            for mod in mesh.modifiers:
                print(mod.name)
                bpy.ops.object.modifier_apply(modifier=mod.name)


    @staticmethod
    def get_or_create_collection_path(collection_path):
        """
        get or create collection from provided collections path,
        we need ommit first element because its base scene collection
        """
        print("SEARCH: %s" % collection_path)
        current_collection = bpy.context.scene.collection
        for collection_name in collection_path.split("/")[2:]:
            collection = current_collection.children.get(collection_name)
            if not collection:
                print("NEEED TO CREATE: %s" % collection_name)
                collection = bpy.data.collections.new(collection_name)
                current_collection.children.link(collection)
            current_collection = collection            
        return current_collection

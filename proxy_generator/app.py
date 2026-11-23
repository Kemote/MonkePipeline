import bpy

from exporter.collectors import collector_assets
from exporter.layers_exporters.common import PROXY_POST_FIX, is_lod_set
from exporter.layers_exporters.physics import is_collisions_collection_name
from exporter.monke_logging import get_logger


logger = get_logger(__name__)
VISUALS_COLLECTION_PREFIX = "visuals"
# kept in the prim name: a visuals proxy sits next to its render mesh, so the names must differ
VISUAL_PROXY_POST_FIX = "_proxy"


def is_visuals_collection_name(name):
    return name.lower().startswith(VISUALS_COLLECTION_PREFIX)


class ProxyGenerator:
    """
    generates decimated proxy meshes, in one of two modes:
    - lod: the asset has a 'lod_VAR_render' collection, its meshes are copied into a 'lod_VAR_proxy' tree
    - visuals: otherwise every mesh inside a 'visuals*' collection gets a '<name>_proxy' sibling in the
      same collection, so it ends up under the same prim as its render mesh. That keeps the proxy under
      the link's rigid body, so it follows the simulation like the render mesh does
    collision meshes and rigid bodies are never copied in either mode: a copy keeps its rigid body
    settings, and a second set of colliders would fight the real ones in the simulation
    """
    def __init__(self, asset_item: collector_assets.CollectedAssetItem , decimate_ratio=0.025):
        self.asset_item = asset_item
        self.mesh_objects = asset_item.mesh_objects
        self.decimate_ratio = decimate_ratio
        self.proxy_collections = []
        self.proxy_meshes = []

    def add_proxy(self):
        lod_variants = next(
            (var_dict for var_set_name, var_dict in self.asset_item.variant_root.variant_sets.items() if is_lod_set(var_set_name)),
            None,
        )
        if lod_variants is not None:
            self._add_lod_proxy(lod_variants)
        else:
            self._add_visuals_proxy(self.asset_item.variant_root)

    def _add_lod_proxy(self, var_dict):
        render_node: collector_assets.VariantNode = var_dict.get("render")
        if not render_node:
            logger.error("Cannot find 'render' group in 'lod' variant collection")
            raise KeyError("Cannot find 'render' group in 'lod' variant collection")
        logger.debug("Creating proxy meshes for lod...")
        proxy_node = collector_assets.VariantNode()
        var_dict["proxy"] = proxy_node
        for outliner_path in render_node.outliner_paths:
            self._add_proxy_mesh(outliner_path, proxy_node, add_postfix=False)

        self._add_subvariants(render_node.variant_sets, proxy_node)

    def _add_visuals_proxy(self, node: collector_assets.VariantNode):
        # iterate over a copy: the proxies are appended to the same node
        for outliner_path in list(node.outliner_paths):
            if not self._is_visual(outliner_path) or self._is_collision(outliner_path):
                continue
            proxy_path = self._add_visual_proxy_mesh(outliner_path)
            node.outliner_paths.append(proxy_path)
            self.asset_item.proxy_paths[outliner_path] = proxy_path

        for variants in node.variant_sets.values():
            for variant_node in variants.values():
                self._add_visuals_proxy(variant_node)

    def _add_visual_proxy_mesh(self, source_path):
        src_mesh = self.mesh_objects[source_path]
        collection_path = source_path.rsplit("/", 1)[0]
        # the source's own collection: not added to proxy_collections, clear() must not remove it
        target_collection = self.get_or_create_collection_path(collection_path)
        mesh = self._create_mesh_copy(src_mesh, target_collection, self.decimate_ratio, VISUAL_PROXY_POST_FIX)
        self.proxy_meshes.append(mesh)
        # Blender may suffix the name (.001) when it's taken, so the path uses the final name
        proxy_path = f"{collection_path}/{mesh.name}"
        self.mesh_objects[proxy_path] = mesh
        return proxy_path

    def _is_visual(self, outliner_path):
        relative = outliner_path[len(self.asset_item.path):]
        return any(is_visuals_collection_name(part) for part in relative.split("/")[:-1])

    def _is_collision(self, outliner_path):
        if self.mesh_objects[outliner_path].rigid_body:
            return True
        relative = outliner_path[len(self.asset_item.path):]
        return any(is_collisions_collection_name(part) for part in relative.split("/"))

    def _add_subvariants(self, variant_sets_dict, proxy_node: collector_assets.VariantNode):
        for variant_set_name, variant_dict in variant_sets_dict.items():
            for variant_name, variant_node in variant_dict.items():
                proxy_variant_node = proxy_node.add_variant(variant_set_name, variant_name)
                for outliner_path in variant_node.outliner_paths:
                    self._add_proxy_mesh(outliner_path, proxy_variant_node)
                self._add_subvariants(variant_node.variant_sets, proxy_variant_node)

    def clear(self):
        for mesh in self.proxy_meshes:
            bpy.data.objects.remove(mesh, do_unlink=True)
        bpy_collections = bpy.data.collections
        self.proxy_collections.reverse()
        for proxy_collection in self.proxy_collections:
            try:
                bpy_collections.remove(proxy_collection, do_unlink=True)
            except Exception as err:
                logger.warning(f"An error occure during cleaning scene from proxy meshes: {err}")
        self.asset_item.proxy_paths.clear()

    def generate_proxy(self, source_mesh, source_path, add_postfix):
        """
        method which generate lod proxy mesh and put it to the appropriate collection
        return mesh object and it's scene path
        """
        target_path = source_path.replace(f"{collector_assets.VARIANT_SEPARATOR}render",
                                          f"{collector_assets.VARIANT_SEPARATOR}proxy")
        target_collection_parts = target_path.split("/")
        target_collection_path = "/".join(target_collection_parts[:-1])
        if add_postfix:
            target_collection_path = f"{target_collection_path}{PROXY_POST_FIX}"
        # every collection made on the way is recorded, not only the last one, so clear() leaves
        # no empty 'lod_VAR_proxy' tree behind in the .blend
        target_collection = self.get_or_create_collection_path(target_collection_path, self.proxy_collections)
        mesh = self._create_mesh_copy(source_mesh, target_collection, self.decimate_ratio)
        scene_path = f"{target_collection_path}/{mesh.name}"
        self.proxy_meshes.append(mesh)
        return mesh, scene_path

    def _add_proxy_mesh(self, source_path, proxy_node: collector_assets.VariantNode, add_postfix=True):
        if self._is_collision(source_path):
            logger.debug(f"Skipping proxy for collision mesh: {source_path}")
            return
        src_mesh = self.mesh_objects[source_path]
        proxy_mesh, proxy_scene_path = self.generate_proxy(src_mesh, source_path, add_postfix)
        # add proxy paths to item
        self.mesh_objects[proxy_scene_path] = proxy_mesh
        proxy_node.outliner_paths.append(proxy_scene_path)

    def _create_mesh_copy(self, mesh, target_collection, decimate_ratio, postfix=PROXY_POST_FIX):
        proxy_name = f"{mesh.name}{postfix}"
        new_mesh = mesh.copy()
        new_mesh.data = mesh.data.copy()
        new_mesh.name = proxy_name
        target_collection.objects.link(new_mesh)
        self.reduce_polycount(new_mesh, decimate_ratio)
        return new_mesh

    @staticmethod
    def reduce_polycount(mesh, decimate_ratio):
        logger.debug("Reducing polycount")
        decimate_mod = mesh.modifiers.new("proxy_generator_decimate", "DECIMATE")
        decimate_mod.ratio = decimate_ratio
        with bpy.context.temp_override(active_object=mesh, selected_editable_objects=[mesh]):
            bpy.context.view_layer.objects.active = mesh
            bpy.ops.object.modifier_apply(modifier=decimate_mod.name)

    @staticmethod
    def get_or_create_collection_path(collection_path, created=None):
        """
        get or create collection from provided collections path,
        we need ommit first element because its base scene collection.
        Collections it creates are appended to `created`, parents before children
        """
        logger.debug(f"Searching for collection: {collection_path}")
        current_collection = bpy.context.scene.collection
        for collection_name in collection_path.split("/")[2:]:
            collection = current_collection.children.get(collection_name)
            if not collection:
                logger.debug(f"No {collection_name} collection found, creating it")
                collection = bpy.data.collections.new(collection_name)
                current_collection.children.link(collection)
                if created is not None:
                    created.append(collection)
            current_collection = collection
        return current_collection

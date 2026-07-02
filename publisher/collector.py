import bpy

from abc import ABC, abstractmethod


VARIANT_SEPARATOR = "_VAR_"


class VariantNode:
    """
    one level of an asset's variant hierarchy.

    outliner_paths: outliner paths of the meshes that live directly at this level
    variant_sets: {variant_set_name: {variant_name: VariantNode}} - a variant may
                  itself own further variant sets, so the tree nests to any depth
    """
    def __init__(self):
        self.outliner_paths = []
        self.variant_sets = {}

    def add_variant(self, variant_set_name, variant_name):
        variant_set = self.variant_sets.setdefault(variant_set_name, {})
        node = variant_set.get(variant_name)
        if node is None:
            node = variant_set[variant_name] = VariantNode()
        return node


class CollectedItem():
    def __init__(self, name, outliner_path):
        self.name = name
        self.outliner_path = outliner_path
        self.type = "BASE_ITEM"
        # root of the variant hierarchy; variant_root.outliner_paths are the meshes
        # that belong to the asset regardless of any variant selection
        self.variant_root = VariantNode()


class CollectedAssetItem(CollectedItem):
    """
    mesh_objects: dict mapping a mesh's outliner path -> its Blender object, for
    every mesh in the asset (across all variant levels)
    """
    def __init__(self, name, outliner_path):
        super().__init__(name, outliner_path)
        self.mesh_objects = {}
        self.type = "ASSET_ITEM"


class Collector(ABC):
    def __init__(self):
        self.items = []

    @abstractmethod
    def collect(self, outliner_base_path: str, object_type: str):
        """
        method assets gathering data for publish purpose
        """
        if not outliner_base_path.startswith("/"):
            raise ValueError(f"Outliner base path: {outliner_base_path}, should starts with '/'")

        self.items = []     # reset items list so it will not duplicate elements in case user use it more than once
        assets_collection = self.find_collection(outliner_base_path)
        if assets_collection:
            for asset_group in assets_collection.children:
                asset_name = asset_group.name
                group_path = f"{outliner_base_path}/{asset_name}"
                asset_item = CollectedAssetItem(asset_name, group_path)
                self.collect_variants(asset_group, group_path, object_type, asset_item, asset_item.variant_root)
                self.items.append(asset_item)
        return

    def collect_variants(self, collection: bpy.types.Collection, outliner_path: str, obj_type: str, asset_item, node):
        """
        walks a collection subtree building the asset's variant hierarchy.

        meshes sitting directly in `collection` belong to `node`. a child
        collection named "setName{VARIANT_SEPARATOR}variantName" opens a nested
        variant level and is recursed into on its own VariantNode, so nesting
        (e.g. modelType_VAR_tree > lod_VAR_high) is preserved to any depth. any
        other child collection is plain organisation and keeps the current node.
        """
        for obj in collection.objects:
            if obj.type == obj_type:
                obj_path = f"{outliner_path}/{obj.name}"
                asset_item.mesh_objects[obj_path] = obj
                node.outliner_paths.append(obj_path)

        for child in collection.children:
            child_path = f"{outliner_path}/{child.name}"
            splited_name = child.name.split(VARIANT_SEPARATOR)
            if len(splited_name) > 1:
                variant_set_name, variant_name = splited_name[0], splited_name[-1]
                child_node = node.add_variant(variant_set_name, variant_name)
                self.collect_variants(child, child_path, obj_type, asset_item, child_node)
            else:
                self.collect_variants(child, child_path, obj_type, asset_item, node)

    def find_collection(self, path: str):
        parts = [part for part in path.split("/") if part]
        if not parts:
            return None

        collection = bpy.context.scene.collection
        for index, part in enumerate(parts):
            if index == 0 and collection.name == part:
                continue
            collection = collection.children.get(part)
            if collection is None:
                return None
        return collection
    

class AssetsCollector(Collector):
    def __init__(self):
        super().__init__()

    def collect(self, assets_path="/Scene/Assets"):
        super().collect(assets_path, "MESH")
        return

    def get_usd_export_data(self):
        """
        builds the per-mesh data required to author OpenUSD prims (mesh geometry,
        world transform, assigned materials) from the mesh objects gathered by collect()
        """
        export_data = []
        for asset_item in self.items:
            asset_export = {
                "name": asset_item.name,
                "outliner_path": asset_item.outliner_path,
                "meshes": [],
            }
            for outliner_path, mesh_obj in asset_item.mesh_objects.items():
                asset_export["meshes"].append({
                    "name": mesh_obj.name,
                    "outliner_path": outliner_path,
                    "matrix_world": mesh_obj.matrix_world.copy(),
                    "mesh_data": mesh_obj.data,
                    "materials": [slot.material for slot in mesh_obj.material_slots if slot.material],
                })
            asset_export["meshes"].sort(key=lambda mesh: mesh["outliner_path"])
            export_data.append(asset_export)
        return export_data


class LightCollector(Collector):
    def __init__(self):
        super().__init__()

    def collect(self):
        return super().collect()

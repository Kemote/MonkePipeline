import bpy

from abc import ABC, abstractmethod


VARIANT_SEPARATOR = "_VAR_"


class CollectedItem():
    def __init__(self, name, outliner_path):
        """
        self._base_objects: base objects of type scene outliner path
        self._varaints: 
        """
        self.name = name
        self.outliner_path = outliner_path
        self.type = "BASE_ITEM"
        self.base_objects = []
        self.variants = {}

    def has_variants(self):
        if self.variants and len(self.variants) < 2:
            return False
        else:
            return True

    def add_variant(self, variant_set_name, variant_name, oultiner_path):
        variant_set = self._variants.get(variant_set_name)
        if not variant_set:
            variant_set = self._variants[variant_set_name] = {}
        
        variant_objects = variant_set.get(variant_name)
        if not variant_objects:
            variant_objects = self._variants[variant_name] = []
        
        variant_objects.append(oultiner_path)

    # def itter_variants(self):
    #     for variant_set_name, variants_dict in self._variants.items():
    #         if not variant_set_name:
    #             continue
    #         for variant_name, object_list in variants_dict.items():
    #             if not variant_name:
    #                 continue
    #             yield variant_set_name, variant_name, object_list

    # def __repr__(self):
    #     return f"{self.type}(name={self.name!r}, outliner_path={self.outliner_path!r})"


class CollectedAssetItem(CollectedItem):
    """
    mesh_objects list dict contain mesh data over outliner_path key
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
                asset_item = CollectedAssetItem(asset_name,  group_path)
                for mesh_obj, outliner_path, in self.iter_object_type(asset_group, group_path, object_type):
                    asset_item.mesh_objects[outliner_path] = mesh_obj
                    
                    outliner_base_name = outliner_path.split("/")[-1]
                    splited_base_name = outliner_base_name.split(VARIANT_SEPARATOR)
                    if len(splited_base_name) > 1:
                        variant_set_name = splited_base_name[0]
                        variant_name = splited_base_name[-1]
                        asset_item.add_variant(variant_set_name, variant_name, outliner_path)
                    else:
                        asset_item.base_objects.append(outliner_path)

                self.items.append(asset_item)
        return

    def iter_object_type(self, collection: bpy.types.Collection, outliner_path: str, obj_type: str):
        """
        method which allwo to find all object of provided type iside outliner group, by path like: "/collectionName/collectionName2"
        it's yielding base group name and all objects of type inside of it
        """
        for obj in collection.objects:
            if obj.type == obj_type:
                yield obj, f"{outliner_path}/{obj.name}"
        for child in collection.children:
            yield from self.iter_object_type(child, f"{outliner_path}/{child.name}")

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

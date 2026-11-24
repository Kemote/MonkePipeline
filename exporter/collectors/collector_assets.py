import bpy

from abc import ABC, abstractmethod
from exporter.monke_logging import get_logger


logger = get_logger(__name__)
VARIANT_SEPARATOR = "_VAR_"
ASSETS_ROOT = "/Scene Collection/assets"
ARMATURE_COLLECTION_NAME = "armature"
# custom property ProxyGenerator puts on the meshes it creates. They're deleted after each export,
# but a failed export or a save in between can leave them in the scene, so they're never collected
GENERATED_PROXY_PROPERTY = "monke_generated_proxy"


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
        self.path = outliner_path
        self.type = "BASE_ITEM"
        self.variant_root = VariantNode()


class CollectedAssetItem(CollectedItem):
    """
    mesh_objects: {outliner_path: mesh_obj} for all variant levels
    armature_objects: {outliner_path: armature_obj} from armature collection
    materials: {name: material} standard materials
    material_variants: {base_name: {variant_name: material}} single-level variants
    proxy_paths: {render_outliner_path: proxy_outliner_path} visuals proxies made by ProxyGenerator
    """
    def __init__(self, name, outliner_path):
        super().__init__(name, outliner_path)
        self.mesh_objects = {}
        self.armature_objects = {}
        self.materials = {}
        self.material_variants = {}
        self.proxy_paths = {}
        self.type = "ASSET_ITEM"

    def add_material(self, material):
        splited_name = material.name.split(VARIANT_SEPARATOR)
        if len(splited_name) > 1:
            base_name, variant_name = splited_name[0], splited_name[-1]
            self.material_variants.setdefault(base_name, {})[variant_name] = material
        else:
            self.materials[material.name] = material

    # which export steps have data, used by the UI and UsdExporter
    @property
    def has_geometry(self):
        return bool(self.mesh_objects)

    @property
    def has_materials(self):
        return bool(self.materials or self.material_variants)

    @property
    def has_armature(self):
        return bool(self.armature_objects)

    @property
    def has_physics(self):
        return any(mesh_obj.rigid_body for mesh_obj in self.mesh_objects.values())


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

        self.items = [] 
        assets_collection = self.find_collection(outliner_base_path)
        if assets_collection:
            for asset_group in assets_collection.children:
                asset_name = asset_group.name
                group_path = f"{outliner_base_path}/{asset_name}"
                asset_item = CollectedAssetItem(asset_name, group_path)
                self.collect_variants(asset_group, group_path, object_type, asset_item, asset_item.variant_root)
                self._post_collect(asset_group, group_path, asset_item)
                self.items.append(asset_item)
        return

    def _post_collect(self, asset_group, group_path, asset_item):
        pass

    def collect_variants(self, collection: bpy.types.Collection, outliner_path: str, obj_type: str, asset_item, node):
        """
        recursively build variant hierarchy: '_VAR_' collections open nested nodes, others stay inline
        """
        for obj in collection.objects:
            if obj.type == obj_type and not obj.get(GENERATED_PROXY_PROPERTY):
                obj_path = f"{outliner_path}/{obj.name}"
                asset_item.mesh_objects[obj_path] = obj
                node.outliner_paths.append(obj_path)
                for slot in obj.material_slots:
                    if slot.material:
                        asset_item.add_material(slot.material)

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

    def collect(self, assets_path=ASSETS_ROOT):
        super().collect(assets_path, "MESH")
        return

    def _post_collect(self, asset_group, group_path, asset_item):
        """
        armatures sit outside the mesh variant tree and are collected separately here
        """
        armature_collection = next(
            (child for child in asset_group.children if child.name.lower() == ARMATURE_COLLECTION_NAME),
            None,
        )
        if armature_collection is None:
            return

        armature_path = f"{group_path}/{armature_collection.name}"
        self._collect_objects_by_type(armature_collection, armature_path, "ARMATURE", asset_item.armature_objects)

    def _collect_objects_by_type(self, collection, outliner_path, obj_type, target):
        for obj in collection.objects:
            if obj.type == obj_type:
                target[f"{outliner_path}/{obj.name}"] = obj

        for child in collection.children:
            self._collect_objects_by_type(child, f"{outliner_path}/{child.name}", obj_type, target)

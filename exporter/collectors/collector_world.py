import bpy
# from mathutils import Vector, Quaternion, Euler


class InstancerItem:
    def __init__(self, inst_name: str, transform):
        self.asset_name = inst_name
        self.transform = transform

    def __eq__(self, other):
        if other.asset_name == self.asset_name and other.transform == self.transform:
            return True
        else:
            return False

    def __repr__(self):
        rot, loc, scale = self.decompose_transform()
        return f"{self.asset_name} instance at position: {loc}, rotation {rot}, scale: {scale}"

    def decompose_transform(self, rotation_mode="EULER"):
        loc, rot_quat, scale = self.transform
        rot = rot_quat.to_euler('XYZ') if rotation_mode == 'EULER' else rot_quat
        return rot, loc, scale


class CollectorWorld:
    """
    Collects all empty-geometry objects using Geometry Nodes that instance meshes 
    from other collections, extracting world-space Position, Rotation, Scale, 
    and source Collection info for every generated instance.
    """

    def __init__(self, context=None):
        self.context = context or bpy.context
        self.depsgraph = self.context.evaluated_depsgraph_get()
        self.instances_dict = {}

    def has_geonodes_modifier(self, obj: bpy.types.Object) -> bool:
        """Checks if an object has an active Geometry Nodes modifier."""
        if not obj or not hasattr(obj, "modifiers"):
            return False
        return any(
            mod.type == 'NODES' and mod.show_viewport
            for mod in obj.modifiers
        )

    def is_empty_geometry(self, obj: bpy.types.Object) -> bool:
        """
        Checks if the object has zero base vertices/splines 
        (standard empty-mesh container setup for Geometry Nodes).
        """
        if obj.type == 'EMPTY':
            return True
        if obj.type == 'MESH' and obj.data and len(obj.data.vertices) == 0:
            return True
        if obj.type == 'CURVE' and obj.data and len(obj.data.splines) == 0:
            return True
        return False

    def get_target_containers(self, only_empty_geo: bool = True) -> set:
        """Finds all scene objects matching the Geometry Nodes container criteria."""
        containers = set()
        for obj in self.context.scene.objects:
            if self.has_geonodes_modifier(obj):
                if not only_empty_geo or self.is_empty_geometry(obj):
                    containers.add(obj.name)
        return containers

    def get_object_collections(self, obj: bpy.types.Object) -> list[str]:
        """Returns a list of collection names that the source mesh belongs to."""
        return [col.name for col in obj.users_collection]
    

    def get_object_collection_paths(self,
        obj: bpy.types.Object,
        scene: bpy.types.Scene = None,
        separator: str = "/",
        include_scene_root: bool = False
        ) -> list[str]:
        """
        Returns a list of full Outliner hierarchy paths for all collections 
        containing `obj` in the given scene.
        """
        
        # TODO: clean it!!
        scene = scene or bpy.context.scene
        target_cols = set(obj.users_collection)
        paths = []

        def walk(col: bpy.types.Collection, current_path: list[str]):
            # Check if the object is directly linked inside this collection
            if col in target_cols:
                if current_path:
                    paths.append(separator.join(current_path))
                elif include_scene_root:
                    paths.append(col.name)

            # Recurse into child collections
            for child in col.children:
                walk(child, current_path + [child.name])

        root_path = [scene.collection.name] if include_scene_root else []
        walk(scene.collection, root_path)

        return paths
        
    def get_asset_name(self, obj: bpy.types.Object) -> str:
        for collection_path in self.get_object_collection_paths(obj):
            split_path = collection_path.split("/")
            if split_path[0] == "assets" and len(split_path) > 1:
                return split_path[1]
        return None
        
    def collect(
        self,
        only_empty_geo: bool = True,
        source_collections: list[str] | None = None,
    ) -> dict:
        """
        Extracts transforms for all Geometry Nodes instances originating from collections.

        Args:
            only_empty_geo: If True, filters to GN containers with 0 base vertices/splines.
            source_collections: Optional list of collection names to filter by (e.g., ["Trees", "Rocks"]).
                                If None, collects instances from any collection.
            rotation_mode: 'EULER' (radians) or 'QUATERNION'.

        Returns:
            Dict mapping container names to a list of dicts containing instance data.
        """
        target_containers = self.get_target_containers(only_empty_geo=only_empty_geo)
        self.instances_dict = {name: {} for name in target_containers}

        if not target_containers:
            return

        allowed_cols = set(source_collections) if source_collections else None

        for inst in self.depsgraph.object_instances:
            if not inst.is_instance:
                continue

            parent = inst.parent
            if not parent or parent.original.name not in target_containers:
                continue

            # inst.object.original points to the specific mesh inside the instanced collection
            orig_obj = inst.object.original
            
            # ensure the instanced source is a mesh (or remove check if curves/lights are in the collection)
            if orig_obj.type != 'MESH':
                continue

            obj_cols = self.get_object_collections(orig_obj)

            # filter by specific source collections if requested
            if allowed_cols is not None:
                matched_cols = [c for c in obj_cols if c in allowed_cols]
                if not matched_cols:
                    continue
            else:
                matched_cols = obj_cols
            
            asset_name = self.get_asset_name(orig_obj)
            transforms = inst.matrix_world.decompose()
            instancer_path = self.get_object_collection_paths(parent.original)[0]

            instances_list = self.instances_dict.get(instancer_path)
            if not instances_list:
                instances_list = []
                self.instances_dict[instancer_path] = instances_list

            instancer_obj = InstancerItem(asset_name, transforms)
            if instancer_obj not in instances_list:
                instances_list.append(instancer_obj)



# =====================================================================
# Example Usage
# =====================================================================
if __name__ == "__main__":
    collector = CollectorWorld()

    # Collect instances coming from any collection (or pass source_collections=["Props", "Foliage"])
    data = collector.collect(
        only_empty_geo=True,
        source_collections=None, 
    )
    
    import pprint
    pprint.pprint(collector.instances_dict)

    """
    for container_name, instances in data.items():
        print(f"\nGN Container: {container_name} | Total Instances: {len(instances)}")
        for i, item in enumerate(instances[:10]):
            pos = tuple(round(v, 3) for v in item["position"])
            rot = tuple(round(v, 3) for v in item["rotation"])
            scl = tuple(round(v, 3) for v in item["scale"])
            cols = ", ".join(item["source_collections"])
            print(
                f"  [{i}] Mesh: {item['mesh_object']} (from [{cols}]) | "
                f"Pos: {pos} | Rot: {rot} | Scale: {scl}"
            )"""
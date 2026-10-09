import bpy


class BlenderCollection:
    def __init__(self):
        pass

    @staticmethod
    def find_collection(path: str):
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
    
    @staticmethod
    def get_collection_outliner_path(collection_obj, include_root=False):
        """
        Return the full path of a collection, e.g. /coll1/coll2/coll3
        """
        names = [collection_obj.name]
        current = collection_obj

        while True:
            parent = next(
                (c for c in bpy.data.collections if current.name in c.children),
                None,
            )
            if parent is None:
                break
            names.append(parent.name)
            current = parent

        if include_root:
            names.append(bpy.context.scene.collection.name)

        return "/Scene Collection/" + "/".join(reversed(names))

    @staticmethod
    def get_selected_collections_objs():
        """
        Return paths of collections selected in the Outliner.
        """
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'OUTLINER':
                    continue
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is None:
                    continue
                with bpy.context.temp_override(window=window, area=area, region=region):
                    return [
                        id_data
                        for id_data in bpy.context.selected_ids
                        if isinstance(id_data, bpy.types.Collection)
                    ]
        return None

    @classmethod
    def get_selected_colections(cls):
        selected_collections_obj = cls.get_selected_collections_objs()
        if selected_collections_obj:
            return [
                cls.get_collection_outliner_path(id_data)
                for id_data in selected_collections_obj
            ]

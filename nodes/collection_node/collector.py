from utils.blender import *
from utils.monke_logging import get_logger
from collections import deque


logger = get_logger(__name__)
VARIANT_PREFIX = "VAR_"


class CollectionItem:
    def __init__(self, parent, prim_path, objects):
        if parent:
            self.has_skeleton = parent.has_skeleton
        else:
            self.has_skeleton = False 
        self.parent = parent
        self.prim_path = prim_path
        self.is_root = False
        
        self.meshs = []
        self.lights = []
        self.curves = []

        self.variants = []        
        self.children = []
    
        self.filter_objects(objects)

    def filter_objects(self, objects):
        for obj in objects:
            if obj.type == "MESH":
                mesh_obj = MeshObject(obj)
                if mesh_obj.armature:
                    self.has_skeleton = True
                    if not self.parent.has_skeleton:
                        splited_path = self.prim_path.split("/")
                        start_path = "/".join(splited_path[:-1])
                        self.prim_path += (f"{start_path}/Rig/{splited_path[-1]}")
                self.meshs.append(mesh_obj)
            
            elif obj.type == "LIGHT":
                self.lights.append(BaseObject(obj))
            
            elif obj.type == "CURVE":
                self.curves.append(BaseObject(obj))
            
            else:
                logger.warning(f"Unsupported object type: {obj.type} for object {obj.name}")


class CollectionRootItem(CollectionItem):
    def __init__(self, parent, prim_path, objects):
        super().__init__(parent, prim_path, objects)
        self.is_root = True


class BaseObject:
    def __init__(self, obj):
        self.obj = obj
        self.xform_animation = obj.animation_data is not None and obj.animation_data.action is not None


class MeshObject(BaseObject):
    def __init__(self, obj):
        super().__init__(obj)
        self.is_skinned = None
        self.armature = None
        self.materials = [slot.material for slot in obj.material_slots if slot.material is not None]
        self.physics_data = {}

        self._check_armature_animation()
        self._get_physical_properties()

    def _check_armature_animation(self):
        parent = self.obj.parent
        has_armature_parent = (parent is not None and parent.type == 'ARMATURE')
        is_parent_deform = (has_armature_parent and self.obj.parent_type == 'ARMATURE')
        has_armature_modifier = any(
            mod.type == 'ARMATURE' and mod.show_viewport for mod in self.obj.modifiers
        )

        self.is_skinned = is_parent_deform or has_armature_modifier
        if has_armature_parent:
            self.armature = parent
            
    def _get_physical_properties(self):
        if not self.obj:
            return {}

        # 1. Rigid Body Physics
        if getattr(self.obj, "rigid_body", None) is not None:
            rb = self.obj.rigid_body
            self.physics_data["rigid_body"] = {
                "type": rb.type,  # 'ACTIVE' or 'PASSIVE'
                "mass": rb.mass,
                "friction": rb.friction,
                "restitution": rb.restitution,
                "collision_shape": rb.collision_shape
            }

        # 2. Physics Modifiers (Cloth, Soft Body, Collision, Fluid)
        if hasattr(self.obj, "modifiers"):
            modifiers_physics = []
            for mod in self.obj.modifiers:
                if mod.type == 'CLOTH':
                    modifiers_physics.append({
                        "type": "CLOTH",
                        "mass": mod.settings.mass,
                        "tension_stiffness": mod.settings.tension_stiffness
                    })
                elif mod.type == 'COLLISION':
                    modifiers_physics.append({
                        "type": "COLLISION",
                        "damping": mod.settings.damping,
                        "friction": mod.settings.friction_factor
                    })
                elif mod.type in {'SOFT_BODY', 'FLUID', 'DYNAMIC_PAINT'}:
                    modifiers_physics.append({"type": mod.type})

            if modifiers_physics:
                self.physics_data["physics_modifiers"] = modifiers_physics


class Collector:
    """
    Basci collector class that collects all objects in a given collection and its children.
    """
    def collect(self, collection_path):
        collection = find_collection(collection_path)
        
        if not collection:
            logger.warning(f"Collection '{collection_path}' not found, skipping")
            return None

        root_item = CollectionRootItem(None, f"/{collection_path.split('/')[-1]}", collection.objects)
        queue = deque([(root_item, collection.children)])

        while queue:
            current_item, current_children = queue.popleft()
            for child in current_children:
                child_item = CollectionItem(current_item, f"{current_item.prim_path}/{child.name}", child.objects)
                # here its decide if current collection is children prim or variant set
                if child.name.startswith(VARIANT_PREFIX):
                    current_item.variants.append(child_item)
                else:
                    current_item.children.append(child_item)
                
                queue.append((child_item, child.children))
        
        return root_item
how a

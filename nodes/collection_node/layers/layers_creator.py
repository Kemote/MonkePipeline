from nodes.collection_node.collector import CollectionItem
from pxr import Usd, Sdf, UsdGeom, UsdShade, UsdLux, UsdSkel, Kind


def copy_prim_structure_only(src_layer, src_path, dst_layer, dst_path=None):
    if dst_path is None:
        dst_path = src_path

    src_spec = src_layer.GetPrimAtPath(src_path)
    if not src_spec:
        return

    dst_spec = Sdf.CreatePrimInLayer(dst_layer, dst_path)
    dst_spec.typeName = src_spec.typeName
    dst_spec.specifier = src_spec.specifier

    for child_spec in src_spec.nameChildren:
        copy_prim_structure_only(
            src_layer, 
            child_spec.path, 
            dst_layer, 
            dst_path.AppendChild(child_spec.name)
        )


class LayerCreator:
    def __init__(self, root_item : CollectionItem):
        self.collected_item = root_item
        self.has_skeleton = root_item.has_skeleton
        self.variants_layer_dict = {}

        self.geom_layer = Usd.Stage.CreateInMemory("geometry_layer")
        self.mat_layer = Sdf.Layer.CreateAnonymous("materials_layer")
        self.rig_layer = Sdf.Layer.CreateAnonymous("armature_layer")
        self.anim_layer = Sdf.Layer.CreateAnonymous("animations_layer")
        self.curves_layer = Sdf.Layer.CreateAnonymous("curves_layer")
        self.lights_layer = Sdf.Layer.CreateAnonymous("lights_layer")
        self.physic_layer = Sdf.Layer.CreateAnonymous("physic_layer")
        
        self.all_layers = [
            self.geom_layer,
            self.mat_layer,
            self.rig_layer,
            self.anim_layer,
            self.curves_layer,
            self.lights_layer,
            self.physic_layer
        ]
        
    def create(self, item : CollectionItem = None):
        if not item:
            item = self.root_item

            # create main prim
            split_path = item.prim_path.split("/")
            main_prim_name = split_path[1]
            for layer in self.all_layers:
                root_prim = Sdf.CreatePrimInLayer(layer, Sdf.Path(f"/{main_prim_name}"))
                root_prim.typeName = "Xform"
                root_prim.specifier = Sdf.SpecifierDef
                root_prim.kind = Kind.Tokens.component
                layer.defaultPrim(main_prim_name)

            # create Geom scope and option SkelRoot
            if item.has_skeleton:
                root_prim = Sdf.PrimSpec(root_prim, "Rig", Sdf.SpecifierDef, "SkelRoot")
            
            geom_scope = Sdf.CreatePrimInLayer(self.geom_layer, Sdf.Path(f"/{str(root_prim.prim_path)}/Geom"))
            geom_scope.typeName = "Scope"
            geom_scope.specifier = Sdf.SpecifierDef

            # create Material Scope
            mat_scope = Sdf.CreatePrimInLayer(self.mat_layer, Sdf.Path(f"/{main_prim_name}/Materials"))
            mat_scope.typeName = "Scope"
            mat_scope.specifier = Sdf.SpecifierDef

            # create Lights Scope
            lights_scope = Sdf.CreatePrimInLayer(self.lights_layer, Sdf.Path(f"/{main_prim_name}/Lights"))
            lights_scope.typeName = "Scope"
            lights_scope.specifier = Sdf.SpecifierDef

        self.process_mehses(item)
        self.process_lights(item)
        self.process_curves(item)

        if item.variants:
            self.add_variatns(item.variants)

        for child in item.children:
            self.create(child)

    def process_mehses(self, item):
        mesh_prim_creator = MeshPrimCreator(item, self.geom_layer, self.mat_layer, self.rig_layer, self.anim_layer, self.physic_layer)
        mesh_prim_creator.create()

    def process_lights(self, item):
        pass

    def process_curves(self, item):
        pass

    def process_armature(self, item):
        pass

    def process_materials(self, item):
        pass

    def bake_animation(self, item):
        pass

    def add_variatns(self, variants):
        for variant in variants:
            self._add_variant()

    def _add_variant(self, variant):
        pass


class MeshPrimCreator:
    def __init__(self, item, geom_layer, mat_layer, rig_layer, anim_layer, physic_layer):
        self.main_prim = None

        self.item = item
        self.geom_layer = geom_layer
        self.mat_layer = mat_layer
        self.rig_layer = rig_layer
        self.anim_layer = anim_layer
        self.physic_layer = physic_layer

    def create(self):
        split_path = self.item.prim_path.split("/")
        skel_root_path = "/".join(split_path[:-2])
        if split_path[-2] == "Rig" and not Sdf.Layer.GetPrimAtPath(skel_root_path):
            skel_root_prim = 
            

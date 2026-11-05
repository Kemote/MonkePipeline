from nodes.collection_node.collector import Item
from pxr import Usd, Sdf, UsdGeom, UsdShade, UsdLux, UsdSkel


class LayerCreator:
    def __init__(self, root_item : Item):
        self.collected_item = root_item
        
        self.geometry_layer = Sdf.Layer.CreateAnonymous("geometry_layer")
        self.materials_layer = Sdf.Layer.CreateAnonymous("materials_layer")
        self.armature_layer = Sdf.Layer.CreateAnonymous("armature_layer")
        self.animations_layer = Sdf.Layer.CreateAnonymous("animations_layer")
        self.curves_layer = Sdf.Layer.CreateAnonymous("curves_layer")
        self.lights_layer = Sdf.Layer.CreateAnonymous("lights_layer")
        self.physic_layer = Sdf.Layer.CreateAnonymous("physic_layer")

    def create(self, item : Item = None):
        if not item:
            item = self.root_item

        self.process_mehses(item.meshs)
        self.process_lights(item.lights)
        self.process_curves(item.curves)
        self.process_materials(item.materials)

        if item.variants:
            self.add_variatns(item.variants)

        for child in item.children:
            self.create(child)

    def process_mehses(self, meshes):
        pass

    def process_lights(self, lights):
        pass

    def process_curves(self, curves):
        pass

    def process_armature(self, armature):
        pass

    def process_materials(self, materials):
        pass

    def bake_animation(self, animation_data):
        pass

    def add_variatns(self, variants):
        for variant in variants:
            self._add_variant()

    def _add_variant(self, variant):
        pass
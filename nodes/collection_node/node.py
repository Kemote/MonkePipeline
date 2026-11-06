from nodes.nodes import *
from nodes.collection_node import AssetArmatureLogic
from nodes.collection_node.collector import Collector
from nodes.collection_node.layers.layers_creator import LayerCreator


class ComponentNode(BaseNode, NodeProperties):
    """
    node representation of scene asset
    """
    __identifier__ = "nodes.component"
    NODE_NAME = "Component node"

    
    def __init__(self):
        super(ComponentNode, self).__init__()
        self.is_cooked = False

        self.add_text_input(
            name="collection_path",
            label="Collection path",
            placeholder_text=""
        )
        self.add_checkbox(
            name="separate_variants",
            label="Separate variants",
            state=True
        )
        self.add_checkbox(
            name="generate_lod",
            label="Generate LOD",
            state=True
        )
        self.add_checkbox(
            name="write_lod_to_sublayers",
            label="Write LOD to sublayers",
            state=True
        )
        # option is available only when LOD is generated, widget signal is emitted on undo too
        self.get_widget("generate_lod").value_changed.connect(
            lambda _, value: self.set_widget_enabled("write_lod_to_sublayers", value)
        )
        # stage settings
        self.add_combo_menu(
            name="up_axis",
            label="Up axis",
            items=["z", "y"]
        )
        self.add_float_input(
            name="meter_per_unit",
            label="Meters per unit",
            value=1.0
        )
        self.add_float_input(
            name="mesh_scale",
            label="Mesh scale",
            value=1.0
        )
        for widget_name in self.view.widgets:
            self.fit_widget_label(widget_name)
        self.view.draw_node()

        self.add_output("geometry", color=ASSET_COL)
        self.add_output("materials", color=ASSET_COL)
        self.add_output("armature", color=ASSET_COL)
        self.add_output("animations", color=ASSET_COL)
        self.add_output("curves", color=ASSET_COL)
        self.add_output("lights", color=ASSET_COL)
        self.add_output("physic", color=ASSET_COL)

    def set_collection_path(self, path_str):
        self.set_property("collection_path", path_str)

    def get_collection_path(self):
        return self.get_property("collection_path")

    def get_export_settings(self):
        return {
            "up_axis": self.get_property("up_axis"),
            "meter_per_unit": self.get_float_property("meter_per_unit"),
            "mesh_scale": self.get_float_property("mesh_scale"),
            # disabled option falls back to default, LOD layers are written as separate files
            "write_lod_to_sublayers": (
                self.get_property("write_lod_to_sublayers") if self.get_property("generate_lod") else True
            ),
        }

    def execute(self, port):
        if not self.is_cooked:
            collector = Collector()
            root_item = collector.collect(self.get_collection_path())
            layer_creator = LayerCreator(root_item)
            layer_creator.create()

            self.is_cooked = True
        
        # port_name = port.name()
        # if port_name == "armature":
        #     armature_logic = AssetArmatureLogic(self)
        #     return armature_logic.execute()


    def _return_geom_data(self):
        if self.collected_item:
            return self.collected_item.mesh_objects
        else:
            return False


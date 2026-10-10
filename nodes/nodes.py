import os

from PySide6 import QtCore
from OdenGraphQt import BaseNode, Port
from OdenGraphQt.constants import PortTypeEnum
from nodes.nodes_logic import UsdOutputExecutor
from publisher.monke_logging import get_logger
from templates.templates import Templates


logger = get_logger(__name__)


ASSET_COL = [160, 210, 255]
USD_COL = [0, 200, 0]


class NodeProperties:
    def __init__(self):
        pass

    @property
    def width(self):
        return self.get_size()[0]

    @property
    def height(self):
        return self.get_size()[1]
    
    def get_size(self):  
        node_size = self.view.boundingRect().size()
        width = node_size.width()
        height = node_size.height()
        return width, height

    
class AssetNode(BaseNode, NodeProperties):
    """
    node representation of scene asset
    """
    __identifier__ = "nodes.asset"
    NODE_NAME = "Asset node"
    DATA_TYPE = "Asset"
    
    def __init__(self):
        super(AssetNode, self).__init__()
        self.collected_item = None
        self.asset_name = None
        
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
        # TODO: dodaj suwak
        self.add_output("geometry", color=ASSET_COL)
        self.add_output("look", color=ASSET_COL)
        self.add_output("armature", color=ASSET_COL)
        self.add_output("physic", color=ASSET_COL)

    @property
    def collected_item(self):
        return self.collected_item

    @property.setter
    def collected_item(self, item):
        self.collected_item = item
        self.asset_name = item.name
        
    def set_collection_path(self, path_str):
        self.set_property("collection_path", path_str)

    def get_collection_path(self):
        return self.get_property("collection_path")

    def compute(self, port_name=None):
        if port_name == "geometry":
            return self._return_geom_data()


    def _return_geom_data(self):
        if self.collected_item:
            return self.collected_item.mesh_objects
        else:
            return False


class UsdOutputNode(BaseNode, NodeProperties):
    """
    node representation of otuput OpenUSD file
    """
    __identifier__ = "nodes.output"
    NODE_NAME = "USD layer output"
    
    def __init__(self):
        super(UsdOutputNode, self).__init__()
        self.templates = Templates()
        self.set_port_deletion_allowed(True)
        self.add_text_input(
            name="output_path",
            label="Output path",
            placeholder_text="./TEST_layer"
        )

        # add autopath checkbox
        self.add_checkbox(
            name="auto_path",
            lable="Auto generated path",
            state=True
        )   

        # USD format combo menu
        self.add_combo_menu(
            name="export_format",
            label="Format",
            items=["usda", "usd", "usdz", "usdc"])

        # inputs (dynamic groups - new port is added when all ports
        # in the group are connected, extra ports are removed on disconnect)
        self.dynamic_inputs = {
            "data": dict(color=ASSET_COL, restrict=self._restrict_to_asset),
            "sublayer": dict(color=USD_COL, restrict=self._restrict_to_layer),
        }
        for base_name in self.dynamic_inputs:
            self._add_dynamic_input(base_name, base_name)

        # outputs
        self.add_output("output path", color=USD_COL)

    # node signals
    def on_input_connected(self, in_port: Port, out_port: Port):
        result = super().on_input_connected(in_port, out_port)

        base_name = self._dynamic_base_name(in_port.name())
        if base_name:
            group_ports = self._dynamic_ports(base_name)
            if all(port.connected_ports() for port in group_ports):
                self._add_dynamic_input(base_name, self._next_dynamic_name(base_name))

        if self.get_property("auto_path").isChecked():
            self._generate_path

        return result

    def on_input_disconnected(self, in_port, out_port):
        result = super().on_input_disconnected(in_port, out_port)

        # ports can't be deleted right away - this is called while the graph
        # iterates over node ports (node deletion) or runs undo commands
        if self._dynamic_base_name(in_port.name()):
            QtCore.QTimer.singleShot(0, self._prune_dynamic_inputs)

        return result

    def execute_graph(self):
        usd_output_executor = UsdOutputExecutor(self)
        result = usd_output_executor.execute()
        return result
    
    def get_format(self):
        return self.get_property("export_format")

    def _generate_path(self):
        assets_names = []
        port_names = []
        ports = self.ports()
        input_types = []
        fields = {"project_name": os.environ.get("PROJECTNAME")}
        
        if len(ports) > 0:
            connected_data_ports = [x for x in ports if x.name().startswith("data")]
            for connected_port in connected_data_ports:
                connected_node = connected_port.parent()
                assets_names.append(connected_node.asset_name)
                port_names.append(connected_port.name())
                input_type = connected_node.DATA_TYPE
                if input_type not in input_types:
                    input_types.append(input_type)

            if len(assets_names) > 1:
                template = self.templates.get_template_by_name("asset_main_file")
                fields["name"] = "assetCollection"
            else:
                template = self.templates.get_template_by_name("asset_sublayer_file")

                # TODO: for assets if more type come it need to be changed
                ports_len = len(port_names)
                types_len = len(input_types)

                # if types_len == 1:
                #     input_type = input_types
                # else:
                #     input_type = "multipleTypes"
                # TODO: its need to be rethinked

                if ports_len == 1:
                    fields["step"] = port_names[0]
                elif ports_len > 1:
                    fields["step"] = "multipleSteps"
                
        file_path = self.templates.resolve_template(template, fields)
        self.get_property("output_path").setText(file_path)

    def _dynamic_base_name(self, port_name):
        for base_name in self.dynamic_inputs:
            if port_name == base_name or port_name.startswith(f"{base_name}_"):
                return base_name
        return None

    def _dynamic_ports(self, base_name):
        return [
            port for name, port in self.inputs().items()
            if self._dynamic_base_name(name) == base_name
        ]

    def _next_dynamic_name(self, base_name):
        num = 2
        while f"{base_name}_{num}" in self.inputs():
            num += 1
        return f"{base_name}_{num}"

    def _add_dynamic_input(self, base_name, port_name):
        settings = self.dynamic_inputs[base_name]
        new_input = self.add_input(port_name, color=settings["color"])
        settings["restrict"](new_input)
        self._sort_dynamic_inputs()
        return new_input

    def _prune_dynamic_inputs(self):
        # node was deleted from the graph in the meantime
        if not self.graph or self.view.scene() is None:
            return

        removed = False
        for base_name in self.dynamic_inputs:
            free_ports = [
                port for port in self._dynamic_ports(base_name)
                if not port.connected_ports()
            ]
            # keep a single free port in the group (base port is never removed)
            if free_ports and free_ports[0].name() != base_name:
                free_ports = free_ports[:-1]
            for port in free_ports:
                if port.name() == base_name:
                    continue
                self.delete_input(port)
                removed = True

        # undo commands keep references to the deleted ports,
        # undoing them would crash the application
        if removed:
            self.graph.clear_undo_stack()

    def _dynamic_sort_key(self, port_name):
        # group order follows self.dynamic_inputs (data above sublayers),
        # inside a group ports are sorted by their number suffix
        base_name = self._dynamic_base_name(port_name)
        if base_name is None:
            return (len(self.dynamic_inputs), 0)
        group_idx = list(self.dynamic_inputs).index(base_name)
        suffix = port_name[len(base_name) + 1:]
        return (group_idx, int(suffix) if suffix.isdigit() else 1)

    def _sort_dynamic_inputs(self):
        # ports are always appended at the bottom, so reorder the node ports,
        # the model and the view items to keep the groups together
        self._inputs.sort(key=lambda port: self._dynamic_sort_key(port.name()))
        self.model.inputs = {port.name(): port.model for port in self._inputs}

        view_items = self.view._input_items
        sorted_items = sorted(view_items.items(), key=lambda item: self._dynamic_sort_key(item[0].name))
        view_items.clear()
        view_items.update(sorted_items)

        if self.view.scene():
            self.view.draw_node()

    def _restrict_to_layer(self, node_input):
        node_input.add_accept_port_type(
            port_name="output path",
            port_type=PortTypeEnum.OUT.value,
            node_type="nodes.output.UsdOutputNode"
        )

    def _restrict_to_asset(self, node_input):
        for port_name in ("geometry", "look", "armature", "physic"):
            node_input.add_accept_port_type(
                port_name=port_name,
                port_type=PortTypeEnum.OUT.value,
                node_type="nodes.asset.AssetNode"
            )
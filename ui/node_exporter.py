import sys

from PySide6 import QtWidgets
from OdenGraphQt import NodeGraph, BaseNode, Port
from OdenGraphQt.constants import PortTypeEnum


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
    
    def __init__(self):
        super(AssetNode, self).__init__()
        self.collected_item = None
        
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

    def set_collection_path(self, path_str):
        self.set_property("collection_path", path_str)


class UsdOutputNode(BaseNode, NodeProperties):
    """
    node representation of otuput OpenUSD file
    """
    __identifier__ = "nodes.output"
    NODE_NAME = "USD layer output"
    
    def __init__(self):
        super(UsdOutputNode, self).__init__()
        self.set_port_deletion_allowed(True)
        self.add_text_input(
            name="output_path",
            label="Output path",
            placeholder_text=""
        )
        self.add_checkbox(
            name="separate_variants",
            label="Separate variants",
            state=True
        )

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

        # combo menu
        self.add_combo_menu(
            name="export_format",
            label="Format",
            items=["usda", "usd", "usdz", "usdc"])

    # node signals
    def on_input_connected(self, in_port: Port, out_port: Port):
        result = super().on_input_connected(in_port, out_port)

        base_name = self._dynamic_base_name(in_port.name())
        if base_name:
            group_ports = self._dynamic_ports(base_name)
            if all(port.connected_ports() for port in group_ports):
                self._add_dynamic_input(base_name, self._next_dynamic_name(base_name))

        return result

    def on_input_disconnected(self, in_port, out_port):
        result = super().on_input_disconnected(in_port, out_port)
        input_name = in_port.name()

        base_name = self._dynamic_base_name(input_name)
        if base_name and input_name != base_name and not in_port.connected_ports():
            self.delete_input(in_port)

        return result

    def get_format(self):
        return self.get_property("export_format")

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


class MonkeNodeGraphWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(MonkeNodeGraphWidget, self).__init__(parent)

        # create node graph (keep a reference so it isn't garbage collected)
        self.node_graph = NodeGraph()

        # nodes registring
        for node in (AssetNode, UsdOutputNode):
            self.node_graph.register_node(node)

        graph_menu = self.node_graph.get_context_menu("graph")
        graph_menu.add_command(
            "Add Node...", lambda graph: graph.toggle_node_search(), "Tab"
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.node_graph.widget)


class MonkeDialog(QtWidgets.QDialog):
    """
    Base standalone dialog
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("USD Export")
        self.setMinimumWidth(1000)

        options_layout = QtWidgets.QVBoxLayout()
        logging_layout = QtWidgets.QVBoxLayout()
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.addLayout(options_layout)
        main_layout.addLayout(logging_layout)

        self.node_graph = MonkeNodeGraphWidget()
        main_layout.addWidget(self.node_graph)
            

if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    dialog = MonkeDialog()
    dialog.show()
    sys.exit(app.exec())
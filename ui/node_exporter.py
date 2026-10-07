import sys

from PySide6 import QtWidgets
from OdenGraphQt import NodeGraph, BaseNode, Port
from OdenGraphQt.constants import PortTypeEnum


ASSET_COL = [160, 210, 255]
USD_COL = [0, 200, 0]


class AssetNode(BaseNode):
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

    def set_collection_path(self, path_str):
        self.set_property("collection_path", path_str)


class UsdOutputNode(BaseNode):
    """
    node representation of otuput OpenUSD file
    """
    __identifier__ = "nodes.output_layer"
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

        # inputs
        self.add_input("data", multi_input=True, color=ASSET_COL)

        # outputs
        sublayer_input = self.add_input("sublayer", color=USD_COL)
        self.next_sublayer_num = 2
        self.sublayer_input_names = ["sublayer"]
        self._restrict_to_layer(sublayer_input)

        # combo menu
        self.add_output("output path", color=USD_COL)
        self.add_combo_menu(
            name="export_format",
            label="Format",
            items=["usda", "usd", "usdz", "usdc"])

    # node signals
    def on_input_connected(self, in_port: Port, out_port: Port):
        result = super().on_input_connected(in_port, out_port)
        
        if in_port.name().startswith("sublayer"):
            new_input_name = f"sublayer_{self.next_sublayer_num}"
            if new_input_name not in self.sublayer_input_names:
                new_input = self.add_input(new_input_name, color=USD_COL)
                self._restrict_to_layer(new_input)
                self.next_sublayer_num += 1
                self.sublayer_input_names.append(new_input.name())
        
        return result

    def on_input_disconnected(self, in_port, out_port):
        result = super().on_input_disconnected(in_port, out_port)
        input_name = in_port.name()
        
        if input_name.startswith("sublayer") and input_name != "sublayer":
            if input_name in self.sublayer_input_names:
                self.delete_input(in_port)
                this_port_num = int(input_name.split("_")[-1])
                self.sublayer_input_names.remove(input_name)
                if this_port_num < len(self.sublayer_input_names):
                    self.next_sublayer_num -= +1

        return result

    def get_format(self):
        return self.get_property("export_format")

    def _restrict_to_layer(self, node_input):
        node_input.add_accept_port_type(
            port_name="output path",
            port_type=PortTypeEnum.OUT.value,
            node_type="nodes.output_layer.UsdOutputNode"
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
import sys

from PySide6 import QtCore, QtWidgets
from OdenGraphQt import NodeGraph, BaseNode, Port, NodeGraphMenu
from OdenGraphQt.constants import PortTypeEnum
from publisher.collector import AssetsCollector


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

    def get_collection_path(self):
        return self.get_property("collection_path")


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

        # ports can't be deleted right away - this is called while the graph
        # iterates over node ports (node deletion) or runs undo commands
        if self._dynamic_base_name(in_port.name()):
            QtCore.QTimer.singleShot(0, self._prune_dynamic_inputs)

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


class MonkeNodeGraphWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(MonkeNodeGraphWidget, self).__init__(parent)

        # create node graph (keep a reference so it isn't garbage collected)
        self.node_graph = NodeGraph()

        # nodes registring and adding them to menu
        graph_menu : NodeGraphMenu = self.node_graph.get_context_menu("graph")
        graph_menu.add_command(
            "Search node", self._search_node, "Tab"
        )

        # create node submenu
        node_menu = graph_menu.add_menu("Add Node")
        menu_cache = {}
        for node in (AssetNode, UsdOutputNode):
            self.node_graph.register_node(node)
            node_identifier = node.__identifier__
            menu = menu_cache.get(node_identifier)
            if not menu:
                menu = self._create_submenus(node_menu, node_identifier)
                menu_cache[node_identifier] = menu

            menu.add_command(
                node.NODE_NAME,
                lambda graph, node_type=node.type_: graph.create_node(node_type)
            )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.node_graph.widget)
        graph_menu.add_separator()

        # add functions
        graph_menu.add_command(
            "Add assets from selected", self._add_assets_from_selection
        )
        graph_menu.add_separator()
        graph_menu.add_command(
            "Delete selected",
            lambda graph: graph.delete_nodes(graph.selected_nodes()),
            "Del"
        )
        
    def _create_submenus(self, node_menu, identifier):
        current_menu = node_menu
        for part in identifier.split(".")[1:-1]:
            submenu = current_menu._menus.get(part)
            if not submenu:
                submenu = current_menu.add_menu(part)
            current_menu = submenu
        return current_menu

    def _search_node(self):
        self.node_graph.toggle_node_search()

    def _add_assets_from_selection(self):
        asset_collector = AssetsCollector()
        asset_collector.collect()
        current_pos = list(self.node_graph.cursor_pos())
        for idx, item in enumerate(asset_collector.items):
            asset_node = self.node_graph.create_node("nodes.asset.AssetNode")
            asset_node.set_name(item.name)
            asset_node.set_collection_path(item.path)
            asset_node.collected_item = item
            if idx > 0:
                current_pos[1] = current_pos[1] + asset_node.height + 50

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
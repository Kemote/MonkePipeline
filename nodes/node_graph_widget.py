import sys

from PySide6 import QtWidgets
from OdenGraphQt import NodeGraph, NodeGraphMenu
from publisher.collector import AssetsCollector
from nodes.nodes import AssetNode, UsdOutputNode


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

        # register nodes and create submenus
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
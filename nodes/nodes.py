import os

from PySide6 import QtCore, QtGui
from OdenGraphQt import BaseNode, Port
from OdenGraphQt.constants import PortTypeEnum
from nodes.nodes_logic import UsdOutputExecutor
from utils.monke_logging import get_logger
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

    def add_float_input(self, name, label, value, min_val=0.0001, max_val=1000.0):
        self.add_text_input(name=name, label=label, text=str(value))
        line_edit = self.get_widget(name).get_custom_widget()
        validator = QtGui.QDoubleValidator(min_val, max_val, 5, line_edit)
        validator.setNotation(QtGui.QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QtCore.QLocale(QtCore.QLocale.Language.C))
        line_edit.setValidator(validator)

    def fit_widget_label(self, name):
        # node widgets are limited to 140px width, which clips longer labels
        group_box = self.get_widget(name).widget()
        group_box.ensurePolished()
        label_width = group_box.fontMetrics().horizontalAdvance(group_box.title()) + 10
        if label_width > group_box.minimumWidth():
            group_box.setMaximumWidth(max(group_box.maximumWidth(), label_width))
            group_box.setMinimumWidth(label_width)

    def set_widget_enabled(self, name, enabled):
        # node widgets have text colors set in style sheets, opacity makes disabled widget grayed out
        widget = self.get_widget(name)
        widget.setEnabled(enabled)
        widget.setOpacity(1.0 if enabled else 0.4)

    def get_float_property(self, name):
        value = self.get_property(name)
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Node '{self.name()}' property '{name}' is not a number: '{value}'")


class ArmatureToIsaacNode(BaseNode, NodeProperties):
    """
    node representation of armature to Isaac conversion
    """
    __identifier__ = "nodes.armature_to_isaac"
    NODE_NAME = "Armature to Isaac"
    
    def __init__(self):
        super(ArmatureToIsaacNode, self).__init__()
        self.add_output("isaac", color=ASSET_COL)
        armature_input = self.add_input("armature", color=ASSET_COL)
        armature_input.add_accept_port_type(
            port_name="armature",
            port_type=PortTypeEnum.OUT.value,
            node_type="nodes.asset.AssetNode"
        )


class UsdOutputNode(BaseNode, NodeProperties):
    """
    node representation of otuput OpenUSD file
    """
    __identifier__ = "nodes.output"
    NODE_NAME = "USD layer output"
    
    def __init__(self):
        super(UsdOutputNode, self).__init__()
        self.templates = Templates()
        self.output_type = None
        self.inputs_names = []
        
        self.set_port_deletion_allowed(True)
        self.add_text_input(
            name="output_path",
            label="Output path",
            placeholder_text="./TEST_layer"
        )

        # add autopath checkbox
        self.add_checkbox(
            name="auto_path",
            label="Auto generated path",
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

    def execute(self):
        usd_output_executor = UsdOutputExecutor(self)
        result = usd_output_executor.execute()
        return result
    
    # node signals
    def on_input_connected(self, in_port: Port, out_port: Port):
        result = super().on_input_connected(in_port, out_port)

        base_name = self._dynamic_base_name(in_port.name())
        if base_name:
            group_ports = self._dynamic_ports(base_name)
            if all(port.connected_ports() for port in group_ports):
                self._add_dynamic_input(base_name, self._next_dynamic_name(base_name))

        inputed_node = out_port.node()
        if inputed_node.type_ == "nodes.asset.AssetNode":
            if not self.output_type:
                self.output_type = "Asset"
                self.inputs_names.append(inputed_node.asset_name)
            elif self.output_type != "Asset":
                self.output_type = "Mixed"

        if self.get_property("auto_path"):
            self._generate_output_path()

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

    def _generate_output_path(self):
        assets_names = {"data": [], "sublayer": []}
        port_names = {"data": [], "sublayer": []}
        nodes_identifiers = {"data": [], "sublayer": []}
        fields = {"project_name": os.environ.get("PROJECTNAME")}

        input_ports = self.input_ports()
        for input_port in input_ports:
            port_type = input_port.name().split("_")[0]
            connected_ports = input_port.connected_ports()
            if connected_ports:
                for connected_port in connected_ports:
                    # itterate thorugh ports connected to node                    
                    connected_node = connected_port.node()
                    identifier = connected_node.type_

                    # obtain asset name
                    if identifier == "nodes.asset.AssetNode":
                        asset_name = connected_node.asset_name
                        if asset_name not in assets_names[port_type]:
                            assets_names[port_type].append(asset_name)

                    elif identifier == "nodes.output.UsdOutputNode":
                        if connected_node.output_type == "Asset":
                            for asset_name in connected_node.inputs_names:
                                if asset_name not in assets_names[port_type]:
                                    assets_names[port_type].append(asset_name)

                    # obtain data type
                    if identifier not in nodes_identifiers[port_type]:
                        nodes_identifiers[port_type].append(identifier)

                    # obtain ports names
                    port_name = connected_port.name()
                    if port_name not in port_names[port_type]:
                        port_names[port_type].append(port_name)

        template = None
        data_assets_names = assets_names["data"]
        sublayered_assets_names = assets_names["sublayer"]

        if data_assets_names:
            if len(data_assets_names) > 1:
                template = self.templates.get_template_by_name("asset_main_file")
                fields["name"] = "assetCollection"
            else:
                template = self.templates.get_template_by_name("asset_sublayer_file")
                fields["name"] = data_assets_names[0]

                # TODO: for assets if more type come it need to be changed
                # need to rethink that solution
                ports_len = len(port_names["data"])
                types_len = len(nodes_identifiers["data"])
                if ports_len == 1:
                    fields["step"] = port_names["data"][0]
                elif ports_len > 1:
                    fields["step"] = "multipleSteps"

        if sublayered_assets_names:
            template = self.templates.get_template_by_name("asset_main_file")
            fields["name"] = sublayered_assets_names[0]

        if template and fields:
            file_path = self.templates.get_new_file_path(template, fields)
            self.set_property("output_path", file_path)

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
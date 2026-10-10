import sys
import bpy
import logging

from nodes.node_graph_widget import MonkeNodeGraphWidget, AssetNode, UsdOutputNode
from pathlib import Path
from publisher.exporter import UsdExporter
from publisher.collector import AssetsCollector
from publisher.monke_logging import configure_logging, get_logger
from publisher.proxy_generator.app import ProxyGenerator
from PySide6.QtCore import QLocale, Signal, Slot, QObject, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QComboBox,
    QSlider,
    QSizePolicy,
    QSplitter,
    QWidget
)


STYLE_SHEET_PATH = Path(__file__).parent / "blender_dark_style.qss"
ASSETS_ROOT = "/Scene Collection/assets"
current_dialog = None
configure_logging()
logger = get_logger(__name__)


class QtLogHandler(QObject, logging.Handler):
    log_emitted = Signal(str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        self.log_emitted.emit(msg)


class FloatSlider(QSlider):
    floatValueChanged = Signal(float)

    def __init__(
        self,
        min_val: float = 0.0001,
        max_val: float = 1.0,
        decimals: int = 4,
        orientation=Qt.Orientation.Horizontal,
        parent=None,
    ):
        super().__init__(orientation, parent)
        self.decimals = decimals
        self.factor = 10**decimals
        self.setMinimum(int(min_val * self.factor))
        self.setMaximum(int(max_val * self.factor))
        self.setSingleStep(1)
        self.valueChanged.connect(self._on_value_changed)

    def _on_value_changed(self, value: int):
        self.floatValueChanged.emit(self.value_float())

    def value_float(self) -> float:
        return self.value() / self.factor

    def set_value_float(self, val: float):
        self.setValue(int(round(val * self.factor)))


class StandardGraphCreator:
    def __init__(self, node_graph):
        self.node_graph = node_graph
        self.asset_collector = AssetsCollector()
        self.asset_collector.collect(ASSETS_ROOT)
        
    def create(self):
        self.create_asset_group()

    def create_asset_group(self):
        # create export nodes
        assets_node_list = []
        node_h_margin = 50
        group_h_margin = 100
        node_dist = 500
        new_asset_node_pos = [0.0, 0.0]
        output_height = 0

        for item in self.asset_collector.items:
            asset_node_list = []
            assets_usd_out_list = []

            asset_node : AssetNode = self.node_graph.create_node("nodes.asset.AssetNode")
            asset_node.set_name(item.name)
            asset_node.set_collection_path(item.path)
            asset_node.collected_item = item
            asset_node.set_pos(*new_asset_node_pos)
            new_asset_node_pos[1] += (asset_node.height + node_h_margin)
            asset_node_list.append(asset_node)

            # add separate usd output nodes for every asset
            output_pos = [new_asset_node_pos[0] + asset_node.width + node_dist, None]
            for output_port in asset_node.output_ports():
                usd_out_node : UsdOutputNode = self.node_graph.create_node("nodes.output.UsdOutputNode")
                usd_out_node.set_input(0, output_port)
                usd_out_node.set_name(f"USD {output_port.name()} layer")
                assets_usd_out_list.append(usd_out_node)

                if not output_pos[1]:
                    output_height = usd_out_node.height
                    output_pos[1] = (new_asset_node_pos[1] - (asset_node.height / 2)) - (2 * (output_height + node_h_margin))
                usd_out_node.set_pos(*output_pos)
                output_pos[1] += (output_height + node_h_margin)

            new_asset_node_pos[1] = usd_out_node.pos()[1] + (2 * (output_height + node_h_margin)) + group_h_margin
            
            # add backdrop for this asset outputs
            asset_out_backdrop = self.node_graph.create_node("Backdrop")
            asset_out_backdrop.set_name(f"{item.name} output layers")
            asset_out_backdrop.wrap_nodes(assets_usd_out_list)
            asset_node_list.append(asset_out_backdrop)

            # add assets  main layer
            asset_main_layer_pos = asset_node.pos()
            asset_main_layer_pos[0] = output_pos[0] + node_dist + usd_out_node.width
            asset_main_layer = self.node_graph.create_node("nodes.output.UsdOutputNode")
            for idx, out_node in enumerate(assets_usd_out_list):
                out_port = out_node.get_output("output path")
                asset_main_layer.set_input(idx + 1, out_port)
            asset_main_layer.set_pos(*asset_main_layer_pos)
            asset_main_layer.set_name(f"{item.name} main USD layer")
            
            asset_node_list.extend(assets_usd_out_list)
            asset_node_list.append(asset_main_layer)
            assets_node_list.extend(asset_node_list)
            asset_backdrop = self.node_graph.create_node("Backdrop")
            asset_backdrop.wrap_nodes(assets_node_list)
            asset_backdrop.set_name(f"Asset {item.name} group")
            asset_backdrop.color
            assets_node_list.append(asset_backdrop)

        assets_backdrop = self.node_graph.create_node("Backdrop")
        assets_backdrop.wrap_nodes(assets_node_list)
        assets_backdrop.set_name(f"Collected assets")
            

class MonkeUsdExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Monke OpenUSD Exporter")
        self.setMinimumWidth(1000)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(STYLE_SHEET_PATH.read_text())

        main_layout = QVBoxLayout(self)
        main_view_layout = QHBoxLayout()
        main_view_layout.setContentsMargins(25, 25, 25, 25)
        btn_layout = QHBoxLayout()

        # toggle button to roll the log panel up to the side
        self.log_toggle_btn = QPushButton("◀")
        self.log_toggle_btn.setFixedWidth(20)
        self.log_toggle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.log_toggle_btn.setToolTip("Collapse / expand logs")
        self.log_toggle_btn.setAutoDefault(False)
        self.log_toggle_btn.clicked.connect(self._toggle_log_panel)
        main_view_layout.addWidget(self.log_toggle_btn)

        # splitter lets the user drag the log panel width
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.splitterMoved.connect(self._update_log_toggle_btn)
        main_view_layout.addWidget(self.splitter)

        log_panel = QWidget()
        logging_layout = QVBoxLayout(log_panel)
        logging_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(log_panel)

        # add node graph
        self.node_graph_widget = MonkeNodeGraphWidget()
        self.node_graph = self.node_graph_widget.node_graph
        self.splitter.addWidget(self.node_graph_widget)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        # add logging
        self.log_display = QPlainTextEdit()
        self.log_display.setDisabled(True)
        logging_layout.addWidget(self.log_display)
        self.log_handler = QtLogHandler()
        self.log_handler.log_emitted.connect(self.append_log)
        formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s', '%H:%M:%S')
        self.log_handler.setFormatter(formatter)
        pipeline_logger = logging.getLogger("mainMonkeLogger")
        pipeline_logger.addHandler(self.log_handler)

        self.splitter.setSizes([400, 1500])

        # add buttons
        export_btn = QPushButton("Export")
        export_btn.setFixedWidth(200)
        export_btn.clicked.connect(self.export)
        btn_layout.addStretch()
        btn_layout.addWidget(export_btn)

        main_layout.addLayout(main_view_layout)
        main_layout.addLayout(btn_layout)

        graph_creator = StandardGraphCreator(self.node_graph)
        graph_creator.create()

        
    def export(self):
        logger.info("Exporting...")
        return
    
#         # collect asset items
#         self.asset_collector = AssetsCollector()
#         self.asset_collector.collect()

#         # extension combo box
#         extension_row = QHBoxLayout()
#         self.extension_combo = QComboBox()
#         self.extension_combo.addItems(["usda", "usd", "usdc", "usdz"])
#         extension_row.addWidget(QLabel("Extension:"))
#         extension_row.addWidget(self.extension_combo)
#         options_layout.addLayout(extension_row)

#         # assets selector
#         options_layout.addWidget(QLabel("Assets to export:"))
#         self.assets_checkboxes = []
#         assets_column = QVBoxLayout()
#         for item in self.asset_collector.items:
#             asseet_checkbox = QCheckBox(item.name)
#             asseet_checkbox.setChecked(True)
#             self.assets_checkboxes.append(asseet_checkbox)
#             assets_column.addWidget(asseet_checkbox)
#         options_layout.addLayout(assets_column)

#         # up axis combo box
#         options_layout.addSpacing(25)
#         options_layout.addWidget(QLabel("Stage settings:"))
#         up_axis_row = QHBoxLayout()
#         self.up_axis_combo = QComboBox()
#         self.up_axis_combo.addItems(["z", "y"])
#         up_axis_row.addWidget(QLabel("Up Axis"))
#         up_axis_row.addWidget(self.up_axis_combo)
#         options_layout.addLayout(up_axis_row)

#         # units per meter
#         units_per_meter_lay = QHBoxLayout()
#         units_per_meter_lay.addWidget(QLabel("Units per meter"))
#         self.meter_per_unit = QLineEdit()
#         self.meter_per_unit.setValidator(self._create_double_validator(0.0001, 1000))
#         self.meter_per_unit.setText("1.0")
#         units_per_meter_lay.addWidget(self.meter_per_unit)
#         options_layout.addLayout(units_per_meter_lay)

#         # mesh scale
#         mesh_scale_lay = QHBoxLayout()
#         mesh_scale_lay.addWidget(QLabel("Mesh scale"))
#         self.mesh_scale = QLineEdit()
#         self.mesh_scale.setValidator(self._create_double_validator(0.0001, 1000))
#         self.mesh_scale.setText("100.0")
#         mesh_scale_lay.addWidget(self.mesh_scale)
#         options_layout.addLayout(mesh_scale_lay)

#         # create proxy settings
#         options_layout.addSpacing(25)
#         options_layout.addWidget(QLabel("Auto Proxy Generation:"))
#         decimate_ratio_lay = QHBoxLayout()
#         decimate_ratio_lay.addWidget(QLabel("Decimate ratio"))
#         self.decimate_slider = FloatSlider()
#         self.decimate_slider.set_value_float(0.025)
#         self.ratio_txt = QLineEdit("0.025")
#         self.ratio_txt.setValidator(self._create_double_validator(0.00001, 1.0))
#         self.ratio_txt.setFixedWidth(100)
#         self.ratio_txt.editingFinished.connect(self._sync_ratio_slider)
#         decimate_ratio_lay.addWidget(self.decimate_slider)
#         decimate_ratio_lay.addWidget(self.ratio_txt)
#         self.decimate_slider.floatValueChanged.connect(self._sync_slider_to_text)
#         self.proxy_generator_check = QCheckBox("Generate proxy LOD")
#         self.proxy_generator_check.setChecked(True)
#         options_layout.addWidget(self.proxy_generator_check)
#         options_layout.addLayout(decimate_ratio_lay)
        
#         # create export option checkers
#         options_layout.addSpacing(25)
#         options_layout.addWidget(QLabel("Include layers:"))
#         self.geometry_check = QCheckBox("Geometry")
#         self.materials_check = QCheckBox("Materials")
#         self.armature_check = QCheckBox("Armature")
#         for check in (
#             self.geometry_check,
#             self.materials_check,
#             self.armature_check,
#         ):
#             check.setChecked(True)
#             options_layout.addWidget(check)

#         # buttons row
#         options_layout.addSpacing(25)
#         export_button = QPushButton("Export")
#         export_button.setDefault(True)
#         cancel_button = QPushButton("Cancel")
#         export_button.clicked.connect(self._export)
#         cancel_button.clicked.connect(self.reject)
#         button_row = QHBoxLayout()
#         button_row.addWidget(export_button)
#         button_row.addWidget(cancel_button)
#         options_layout.addLayout(button_row)

#     def _export(self):
#         settings = self.collect()
#         logger.info("Exporting asset items...")
#         usd_exporter = UsdExporter(settings)
#         asset_items = settings["collected_item"]
#         for asset_item in asset_items:
#             proxy_generator = None
#             if settings["generate_proxy"]:
#                 decimate_ratio = settings["decimate_ratio"]
#                 proxy_generator = ProxyGenerator(asset_item, decimate_ratio)
#                 proxy_generator.add_proxy()
#             usd_exporter.export(asset_item)
#             if proxy_generator:
#                 proxy_generator.clear()
#         logger.info("Exporting completed!")
#         # self.accept()

#     def _create_double_validator(self, min_val, max_val):
#         validator = QDoubleValidator(min_val, max_val, 5, self)
#         validator.setNotation(QDoubleValidator.Notation.StandardNotation)
#         locale = QLocale(QLocale.Language.C)
#         validator.setLocale(locale)
#         return validator

#     def _sync_ratio_slider(self):
#         try:
#             val = float(self.ratio_txt.text())
#             # prevents recursion
#             self.decimate_slider.blockSignals(True)
#             self.decimate_slider.set_value_float(val)
#             self.decimate_slider.blockSignals(False)
#         except ValueError:
#             pass

#     def _sync_slider_to_text(self, val: float):
#         # prevents recursion
#         self.ratio_txt.blockSignals(True)
#         self.ratio_txt.setText(f"{val:.4f}".rstrip('0').rstrip('.'))
#         self.ratio_txt.blockSignals(False)

#     def collect(self):
#         logger.info("Collecting asset items...")
#         selected_assets_names = [x.text() for x in self.assets_checkboxes if x.isChecked()]
#         collected_items = [x for x in self.asset_collector.items if x.name in selected_assets_names]
#         return {
#             "extension": self.extension_combo.currentText(),
#             "export_geometry": self.geometry_check.isChecked(),
#             "export_materials": self.materials_check.isChecked(),
#             "export_armature": self.armature_check.isChecked(),
#             "up_axis": self.up_axis_combo.currentText(),
#             "collected_item": collected_items,
#             "meter_per_unit": float(self.meter_per_unit.text()),
#             "mesh_scale": float(self.mesh_scale.text()),
#             "generate_proxy": self.proxy_generator_check.isChecked(),
#             "decimate_ratio": self.decimate_slider.value_float()
#         }

    @Slot(str)
    def append_log(self, text: str):
        self.log_display.appendPlainText(text)

    def _toggle_log_panel(self):
        log_width, graph_width = self.splitter.sizes()
        total = log_width + graph_width
        if log_width > 0:
            self._last_log_width = log_width
            self.splitter.setSizes([0, total])
        else:
            restored = min(self._last_log_width, total - 100)
            self.splitter.setSizes([restored, total - restored])
        self._update_log_toggle_btn()

    def _update_log_toggle_btn(self, *args):
        collapsed = self.splitter.sizes()[0] == 0
        self.log_toggle_btn.setText("▶" if collapsed else "◀")

    def generate_logs(self):
        logger.debug("DEBUG message.")
        logger.info("INFO message.")
        logger.warning("WARNING message!")
        logger.error("ERROR message!")


def _pump_qt_events():
    app = QApplication.instance()
    if app is not None:
        app.processEvents()

    if current_dialog is None or not current_dialog.isVisible():
        return None
    return 0.02


def _on_dialog_finished(result):
    global current_dialog
    if current_dialog is not None:
        logging.getLogger("mainMonkeLogger").removeHandler(current_dialog.log_handler)
    current_dialog = None

    if result != QDialog.Accepted:
        print("USD export cancelled")


def show_export_dialog():
    global current_dialog

    QApplication.instance() or QApplication(sys.argv)

    dialog = MonkeUsdExportDialog()
    dialog.finished.connect(_on_dialog_finished)
    current_dialog = dialog
    dialog.show()

    if not bpy.app.timers.is_registered(_pump_qt_events):
        bpy.app.timers.register(_pump_qt_events, first_interval=0.02)


class MONKE_OT_usd_export(bpy.types.Operator):
    bl_idname = "monke.usd_export"
    bl_label = "USD Export"
    bl_options = {'REGISTER'}

    def execute(self, context):
        show_export_dialog()
        return {'FINISHED'}


class TOPBAR_MT_monke_pipeline(bpy.types.Menu):
    bl_idname = "TOPBAR_MT_monke_pipeline"
    bl_label = "Monke Pipeline"

    def draw(self, context):
        layout = self.layout
        layout.operator(MONKE_OT_usd_export.bl_idname, text="USD Export")


classes = (
    MONKE_OT_usd_export,
    TOPBAR_MT_monke_pipeline,
)

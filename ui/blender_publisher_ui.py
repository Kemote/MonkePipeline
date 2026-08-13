import sys
import bpy

from pathlib import Path
from publisher.exporter import UsdExporter
from publisher.collector import AssetsCollector
from publisher.proxy_generator.app import ProxyGenerator
from PySide6.QtCore import QLocale
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QComboBox
)


STYLE_SHEET_PATH = Path(__file__).parent / "blender_dark_style.qss"
DEFAULT_OUTPUT = "/home/kemot/Documents/Dev/MonkePipeline/sample_usd_files"


class MonkeUsdExportDialog(QDialog):
    """PySide6 dialog collecting USD export settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("USD Export")
        self.setMinimumWidth(420)
        self.setStyleSheet(STYLE_SHEET_PATH.read_text())
        main_layout = QVBoxLayout(self)
        
        # collect asset items
        self.asset_collector = AssetsCollector()
        self.asset_collector.collect()

        # browse row
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setText(DEFAULT_OUTPUT)
        browse_button = QPushButton("Browse output directory...")
        browse_button.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_button)
        main_layout.addLayout(path_row)

        # assets selector
        self.assets_checkboxes = []
        assets_column = QVBoxLayout()
        for item in self.asset_collector.items:
            asseet_checkbox = QCheckBox(item.name)
            asseet_checkbox.setChecked(True)
            self.assets_checkboxes.append(asseet_checkbox)
            assets_column.addWidget(asseet_checkbox)
        main_layout.addLayout(assets_column)

        # extension combo box
        extension_row = QHBoxLayout()
        self.extension_combo = QComboBox()
        self.extension_combo.addItems(["usda", "usd", "usdc", "usdz"])
        extension_row.addWidget(QLabel("Extension:"))
        extension_row.addWidget(self.extension_combo)
        main_layout.addLayout(extension_row)

        # up axis combo box
        up_axis_row = QHBoxLayout()
        self.up_axis_combo = QComboBox()
        self.up_axis_combo.addItems(["z", "y"])
        up_axis_row.addWidget(QLabel("Up Axis:"))
        up_axis_row.addWidget(self.up_axis_combo)
        main_layout.addLayout(up_axis_row)

        # units per meter
        validator = QDoubleValidator(0.0001, 1000, 1, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        locale = QLocale(QLocale.Language.C)
        validator.setLocale(locale)
        self.meter_per_unit = QLineEdit()
        self.meter_per_unit.setValidator(validator)
        self.meter_per_unit.setText("1.0")
        main_layout.addWidget(self.meter_per_unit)

        # create export option checkers
        self.geometry_check = QCheckBox("Geometry")
        self.materials_check = QCheckBox("Materials")
        self.armature_check = QCheckBox("Armature")
        main_layout.addWidget(QLabel("Include:"))
        for check in (
            self.geometry_check,
            self.materials_check,
            self.armature_check,
        ):
            check.setChecked(True)
            main_layout.addWidget(check)

        # button row
        export_button = QPushButton("Export")
        export_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        export_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(export_button)
        button_row.addWidget(cancel_button)
        main_layout.addLayout(button_row)

    def _asset_checker_state_change(self, state):
        pass

    def _browse(self):
        path, _ = QFileDialog.getExistingDirectory(self, "USD Export Directory", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def collect(self):
        selected_assets_names = [x.text() for x in self.assets_checkboxes if x.isChecked()]
        collected_items = [x for x in self.asset_collector.items if x.name in selected_assets_names]
        return {
            "filepath": self.path_edit.text(),
            "extension": self.extension_combo.currentText(),
            "export_geometry": self.geometry_check.isChecked(),
            "export_materials": self.materials_check.isChecked(),
            "export_armature": self.armature_check.isChecked(),
            "up_axis": self.up_axis_combo.currentText(),
            "collected_item": collected_items,
            "meter_per_unit": float(self.meter_per_unit.text())
        }


# Kept alive here so Qt doesn't garbage-collect the dialog while it's open,
# and so the polling timer below can tell whether it's still on screen.
_current_dialog = None


def _pump_qt_events():
    """bpy.app.timers callback: process pending Qt events without blocking
    Blender's own event loop. dialog.exec() would block Blender's main
    thread until the dialog closes (causing Blender's window to appear
    frozen to the OS); polling like this lets both stay responsive."""
    app = QApplication.instance()
    if app is not None:
        app.processEvents()

    if _current_dialog is None or not _current_dialog.isVisible():
        return None  # dialog closed - stop repeating, unregisters the timer

    return 0.02  # ~50 times/second


def _on_dialog_finished(result):
    global _current_dialog
    dialog = _current_dialog
    _current_dialog = None

    if result != QDialog.Accepted:
        print("USD export cancelled")
        return

    
    settings = dialog.collect()
    usd_exporter = UsdExporter(settings)

    asset_items = settings["collected_item"]
    for asset_item in asset_items:
        # it needs to be controlled by checkbox !!!
        if True:    # if settings["generate_proxy"]
            proxy_generator = ProxyGenerator(asset_item)
            proxy_generator.add_proxy()
        usd_exporter.export(asset_item)


def show_export_dialog():
    """Show the USD export dialog without blocking Blender's main thread.
    Reuses the existing QApplication if Blender (or a prior call) already
    created one - only one may exist per process."""
    global _current_dialog

    QApplication.instance() or QApplication(sys.argv)

    dialog = MonkeUsdExportDialog()
    dialog.finished.connect(_on_dialog_finished)
    _current_dialog = dialog
    dialog.show()

    if not bpy.app.timers.is_registered(_pump_qt_events):
        bpy.app.timers.register(_pump_qt_events, first_interval=0.02)


class MONKE_OT_usd_export(bpy.types.Operator):
    """Open the USD Export dialog"""
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

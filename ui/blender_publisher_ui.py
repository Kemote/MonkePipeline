import sys
import bpy

from pathlib import Path
from publisher.exporter import UsdExporter
from publisher.collector import AssetsCollector
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
DEFAULT_OUTPUT = "/home/kemot/Documents/tmp"


class MonkeUsdExportDialog(QDialog):
    """PySide6 dialog collecting USD export settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("USD Export")
        self.setMinimumWidth(420)
        self.setStyleSheet(STYLE_SHEET_PATH.read_text())

        layout = QVBoxLayout(self)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setText(DEFAULT_OUTPUT)
        browse_button = QPushButton("Browse output directory...")
        browse_button.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_button)
        layout.addLayout(path_row)

        self.extension_combo = QComboBox()
        self.extension_combo.addItems(["usda", "usd", "usdc", "usdz"])
        layout.addWidget(self.extension_combo)
        
        layout.addWidget(QLabel("Include:"))
        self.geometry_check = QCheckBox("Geometry")
        self.materials_check = QCheckBox("Materials")
        self.armature_check = QCheckBox("Armature")

        for check in (
            self.geometry_check,
            self.materials_check,
            self.armature_check,
        ):
            check.setChecked(True)
            layout.addWidget(check)

        button_row = QHBoxLayout()
        export_button = QPushButton("Export")
        export_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        export_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(export_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def _browse(self):
        path, _ = QFileDialog.getExistingDirectory(
            self, "USD Export Path", self.path_edit.text(), "USD (*.usd *.usda *.usdc)"
        )
        if path:
            self.path_edit.setText(path)

    def collect(self):
        return {
            "filepath": self.path_edit.text(),
            "extension": self.extension_combo.currentText(),
            "export_geometry": self.geometry_check.isChecked(),
            "export_materials": self.materials_check.isChecked(),
            "export_armature": self.armature_check.isChecked(),
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
    asset_collector = AssetsCollector()
    asset_collector.collect()
    for asset_item in asset_collector.items:
        print(asset_item.name)
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

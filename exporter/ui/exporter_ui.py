import os
import sys
import bpy
import logging

from pathlib import Path
from pipeline_config import resolve_project_location
from exporter.layers_exporters import UsdExporter
from exporter.layers_exporters.usd_exporter import (
    SUBLAYER_RESOLVER_DEFAULT,
    SUBLAYER_RESOLVER_MONKE,
    SUBLAYER_RESOLVERS,
)
from exporter.collector import AssetsCollector
from exporter.monke_logging import configure_logging, get_logger
from proxy_generator.app import ProxyGenerator
from PySide6.QtCore import QLocale, Signal, Slot, QObject, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QComboBox,
    QSlider
)


STYLE_SHEET_PATH = Path(__file__).resolve().parents[2] / "style" / "blender_dark_style.qss"
PUMP_INTERVAL = 0.02  # seconds between Qt event passes
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


class MonkeUsdExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("USD Export")
        self.setStyleSheet(STYLE_SHEET_PATH.read_text())
        self.setMinimumWidth(400)

        options_layout = QVBoxLayout()
        logging_layout = QVBoxLayout()
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.addLayout(options_layout)
        main_layout.addLayout(logging_layout)
        
        # add logging
        self.log_display = QPlainTextEdit()
        self.log_display.setMinimumWidth(500)
        self.log_display.setDisabled(True)
        logging_layout.addWidget(self.log_display)
        self.log_handler = QtLogHandler()
        self.log_handler.log_emitted.connect(self.append_log)
        formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s', '%H:%M:%S')
        self.log_handler.setFormatter(formatter)
        pipeline_logger = logging.getLogger("mainMonkeLogger")
        pipeline_logger.addHandler(self.log_handler)

        # collect asset items
        self.asset_collector = AssetsCollector()
        self.asset_collector.collect()

        # output folder - PROJECTSROOT/PROJECTNAME, or "<blend name>_usd" next to the .blend
        _, _, self.location_from_env = resolve_project_location(bpy.data.filepath)
        # True once the user picks/types a folder, so we stop following the .blend path
        self.output_dir_edited = False
        options_layout.addWidget(QLabel("Output:"))
        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Save the .blend file or choose a folder")
        self.output_dir_edit.textEdited.connect(self._on_output_dir_edited)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_output_dir)
        output_row.addWidget(QLabel("Folder"))
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(browse_button)
        options_layout.addLayout(output_row)
        self._refresh_output_dir()
        if self.location_from_env:
            self.output_dir_edit.setDisabled(True)
            browse_button.setDisabled(True)
            env_note = QLabel(
                "Project settings override this option "
                "(PROJECTSROOT is set in environment variables)."
            )
            env_note.setWordWrap(True)
            options_layout.addWidget(env_note)

        # how the main file references its sublayers
        resolver_row = QHBoxLayout()
        self.sublayer_resolver_combo = QComboBox()
        self.sublayer_resolver_combo.addItems(SUBLAYER_RESOLVERS)
        self.sublayer_resolver_combo.setCurrentText(
            SUBLAYER_RESOLVER_MONKE if self.location_from_env else SUBLAYER_RESOLVER_DEFAULT
        )
        self.sublayer_resolver_combo.setToolTip(
            "MonkeResolver: monkeDisc:// paths, need the resolver plugin and PROJECTSROOT/PROJECTNAME.\n"
            "Default: plain relative paths to the newest versions, load in any application."
        )
        resolver_row.addWidget(QLabel("Sublayers AssetResolver"))
        resolver_row.addWidget(self.sublayer_resolver_combo)
        options_layout.addLayout(resolver_row)
        options_layout.addSpacing(25)

        # extension combo box
        extension_row = QHBoxLayout()
        self.extension_combo = QComboBox()
        self.extension_combo.addItems(["usda", "usd", "usdc", "usdz"])
        extension_row.addWidget(QLabel("Extension:"))
        extension_row.addWidget(self.extension_combo)
        options_layout.addLayout(extension_row)

        # assets selector
        options_layout.addWidget(QLabel("Assets to export:"))
        self.assets_checkboxes = []
        assets_column = QVBoxLayout()
        for item in self.asset_collector.items:
            asseet_checkbox = QCheckBox(item.name)
            asseet_checkbox.setChecked(True)
            self.assets_checkboxes.append(asseet_checkbox)
            assets_column.addWidget(asseet_checkbox)
        options_layout.addLayout(assets_column)

        # up axis combo box
        options_layout.addSpacing(25)
        options_layout.addWidget(QLabel("Stage settings:"))
        up_axis_row = QHBoxLayout()
        self.up_axis_combo = QComboBox()
        self.up_axis_combo.addItems(["z", "y"])
        up_axis_row.addWidget(QLabel("Up Axis"))
        up_axis_row.addWidget(self.up_axis_combo)
        options_layout.addLayout(up_axis_row)

        # units per meter
        units_per_meter_lay = QHBoxLayout()
        units_per_meter_lay.addWidget(QLabel("Units per meter"))
        self.meter_per_unit = QLineEdit()
        self.meter_per_unit.setValidator(self._create_double_validator(0.0001, 1000))
        self.meter_per_unit.setText("1.0")
        units_per_meter_lay.addWidget(self.meter_per_unit)
        options_layout.addLayout(units_per_meter_lay)

        # mesh scale
        mesh_scale_lay = QHBoxLayout()
        mesh_scale_lay.addWidget(QLabel("Mesh scale"))
        self.mesh_scale = QLineEdit()
        self.mesh_scale.setValidator(self._create_double_validator(0.0001, 1000))
        self.mesh_scale.setText("100.0")
        mesh_scale_lay.addWidget(self.mesh_scale)
        options_layout.addLayout(mesh_scale_lay)

        # create proxy settings
        options_layout.addSpacing(25)
        options_layout.addWidget(QLabel("Auto Proxy Generation:"))
        decimate_ratio_lay = QHBoxLayout()
        decimate_ratio_lay.addWidget(QLabel("Decimate ratio"))
        self.decimate_slider = FloatSlider()
        self.decimate_slider.set_value_float(0.025)
        self.ratio_txt = QLineEdit("0.025")
        self.ratio_txt.setValidator(self._create_double_validator(0.00001, 1.0))
        self.ratio_txt.setFixedWidth(100)
        self.ratio_txt.editingFinished.connect(self._sync_ratio_slider)
        decimate_ratio_lay.addWidget(self.decimate_slider)
        decimate_ratio_lay.addWidget(self.ratio_txt)
        self.decimate_slider.floatValueChanged.connect(self._sync_slider_to_text)
        self.proxy_generator_check = QCheckBox("Generate proxy LOD")
        self.proxy_generator_check.setChecked(True)
        options_layout.addWidget(self.proxy_generator_check)
        options_layout.addLayout(decimate_ratio_lay)
        
        # create export option checkers
        options_layout.addSpacing(25)
        options_layout.addWidget(QLabel("Include layers:"))
        self.geometry_check = QCheckBox("Geometry")
        self.materials_check = QCheckBox("Materials")
        self.armature_check = QCheckBox("Armature")
        self.physics_check = QCheckBox("Physics")
        for check in (
            self.geometry_check,
            self.materials_check,
            self.armature_check,
            self.physics_check,
        ):
            check.setChecked(True)
            options_layout.addWidget(check)

        # buttons row
        options_layout.addSpacing(25)
        export_button = QPushButton("Export")
        export_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        export_button.clicked.connect(self._export)
        cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(export_button)
        button_row.addWidget(cancel_button)
        options_layout.addLayout(button_row)

    def _refresh_output_dir(self):
        """follow the .blend path (or env vars) unless the user chose a folder"""
        if self.output_dir_edited and not self.location_from_env:
            return
        projects_root, project_name, _ = resolve_project_location(bpy.data.filepath)
        if projects_root and project_name:
            self.output_dir_edit.setText(os.path.join(projects_root, project_name))
        else:
            self.output_dir_edit.clear()

    def _on_output_dir_edited(self, text):
        self.output_dir_edited = bool(text.strip())

    def _browse_output_dir(self):
        start_dir = self.output_dir_edit.text() or os.path.dirname(bpy.data.filepath)
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start_dir)
        if folder:
            self.output_dir_edit.setText(folder)
            self.output_dir_edited = True

    def _ensure_blend_saved(self):
        """ask the user to save an unsaved .blend, returns False if they cancel"""
        if bpy.data.filepath:
            return True
        # Qt dialog + EXEC save instead of Blender's file browser: the browser is async
        # and would open behind this always-on-top Qt window
        blend_path, _ = QFileDialog.getSaveFileName(
            self, "Save .blend file before export", os.path.expanduser("~"), "Blender files (*.blend)"
        )
        if not blend_path:
            logger.warning("Export cancelled: the .blend file is not saved")
            return False
        if not blend_path.endswith(".blend"):
            blend_path += ".blend"
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        logger.info(f"Saved .blend file: {blend_path}")
        return True

    def _export(self):
        self._refresh_output_dir()
        if not self.output_dir_edit.text().strip():
            if not self._ensure_blend_saved():
                return
            self._refresh_output_dir()

        settings = self.collect()
        if settings["sublayer_resolver"] == SUBLAYER_RESOLVER_MONKE and not self.location_from_env:
            logger.warning(
                "MonkeResolver selected without PROJECTSROOT set: to load these files set "
                f"PROJECTSROOT={settings['projects_root']} and PROJECTNAME={settings['project_name']}"
            )
        logger.info(f"Exporting asset items to: {self.output_dir_edit.text()}")
        usd_exporter = UsdExporter(settings)
        asset_items = settings["collected_item"]
        for asset_item in asset_items:
            proxy_generator = None
            if settings["generate_proxy"]:
                decimate_ratio = settings["decimate_ratio"]
                proxy_generator = ProxyGenerator(asset_item, decimate_ratio)
                proxy_generator.add_proxy()
            usd_exporter.export(asset_item)
            if proxy_generator:
                proxy_generator.clear()
        logger.info("Exporting completed!")
        # self.accept()

    def _create_double_validator(self, min_val, max_val):
        validator = QDoubleValidator(min_val, max_val, 5, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        locale = QLocale(QLocale.Language.C)
        validator.setLocale(locale)
        return validator

    def _sync_ratio_slider(self):
        try:
            val = float(self.ratio_txt.text())
            # prevents recursion
            self.decimate_slider.blockSignals(True)
            self.decimate_slider.set_value_float(val)
            self.decimate_slider.blockSignals(False)
        except ValueError:
            pass

    def _sync_slider_to_text(self, val: float):
        # prevents recursion
        self.ratio_txt.blockSignals(True)
        self.ratio_txt.setText(f"{val:.4f}".rstrip('0').rstrip('.'))
        self.ratio_txt.blockSignals(False)

    def collect(self):
        logger.info("Collecting asset items...")
        selected_assets_names = [x.text() for x in self.assets_checkboxes if x.isChecked()]
        collected_items = [x for x in self.asset_collector.items if x.name in selected_assets_names]
        output_dir = os.path.normpath(os.path.expanduser(self.output_dir_edit.text().strip()))
        return {
            "projects_root": os.path.dirname(output_dir),
            "project_name": os.path.basename(output_dir),
            "sublayer_resolver": self.sublayer_resolver_combo.currentText(),
            "extension": self.extension_combo.currentText(),
            "export_geometry": self.geometry_check.isChecked(),
            "export_materials": self.materials_check.isChecked(),
            "export_armature": self.armature_check.isChecked(),
            "export_physics": self.physics_check.isChecked(),
            "up_axis": self.up_axis_combo.currentText(),
            "collected_item": collected_items,
            "meter_per_unit": float(self.meter_per_unit.text()),
            "mesh_scale": float(self.mesh_scale.text()),
            "generate_proxy": self.proxy_generator_check.isChecked(),
            "decimate_ratio": self.decimate_slider.value_float()
        }

    @Slot(str)
    def append_log(self, text: str):
        self.log_display.appendPlainText(text)

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
    return PUMP_INTERVAL


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


if __name__ == "__main__":
    show_export_dialog()
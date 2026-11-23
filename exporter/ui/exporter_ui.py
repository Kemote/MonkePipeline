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
from exporter.collectors.collector_assets import AssetsCollector
from exporter.collectors.collector_world import WorldCollector
from exporter.monke_logging import configure_logging, get_logger
from proxy_generator.app import ProxyGenerator
from PySide6.QtCore import QLocale, Signal, Slot, QObject, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QPlainTextEdit,
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
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

        # collect world
        self.world_collector = WorldCollector()
        self.world_collector.collect()

        # output folder - PROJECTSROOT/PROJECTNAME, or "<blend name>_usd" next to the .blend
        _, _, self.location_from_env = resolve_project_location(bpy.data.filepath)
        # True once the user picks/types a folder, so we stop following the .blend path
        self.output_dir_edited = False

        options_layout.addWidget(self._build_output_group())
        options_layout.addWidget(self._build_content_group())
        options_layout.addWidget(self._build_layers_group())
        options_layout.addWidget(self._build_stage_group())
        options_layout.addWidget(self._build_proxy_group())
        options_layout.addStretch()
        self._refresh_layer_checks()

        # buttons row
        export_button = QPushButton("Export")
        export_button.setDefault(True)
        cancel_button = QPushButton("Cancel")
        export_button.clicked.connect(self._export)
        cancel_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(export_button)
        button_row.addWidget(cancel_button)
        options_layout.addLayout(button_row)

    def _build_output_group(self):
        """where files go and how they reference each other"""
        group = QGroupBox("Output")
        form = QFormLayout(group)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Save the .blend file or choose a folder")
        self.output_dir_edit.textEdited.connect(self._on_output_dir_edited)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_output_dir)
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(browse_button)
        form.addRow("Folder", output_row)
        self._refresh_output_dir()
        if self.location_from_env:
            self.output_dir_edit.setDisabled(True)
            browse_button.setDisabled(True)
            env_note = QLabel(
                "Project settings override this option "
                "(PROJECTSROOT is set in environment variables)."
            )
            env_note.setWordWrap(True)
            form.addRow(env_note)

        self.extension_combo = QComboBox()
        self.extension_combo.addItems(["usda", "usd", "usdc", "usdz"])
        form.addRow("Extension", self.extension_combo)

        # how the main file references its sublayers
        self.sublayer_resolver_combo = QComboBox()
        self.sublayer_resolver_combo.addItems(SUBLAYER_RESOLVERS)
        self.sublayer_resolver_combo.setCurrentText(
            SUBLAYER_RESOLVER_MONKE if self.location_from_env else SUBLAYER_RESOLVER_DEFAULT
        )
        self.sublayer_resolver_combo.setToolTip(
            "MonkeResolver: monkeDisc:// paths, need the resolver plugin and PROJECTSROOT/PROJECTNAME.\n"
            "Default: plain relative paths to the newest versions, load in any application."
        )
        form.addRow("Sublayers AssetResolver", self.sublayer_resolver_combo)
        return group

    def _build_content_group(self):
        """what gets exported: the world and/or individual assets"""
        group = QGroupBox("Content")
        column = QVBoxLayout(group)

        self.export_world_check = QCheckBox("Export world")
        self.export_world_check.setChecked(True)
        self.export_world_check.setToolTip("Export the scene layout gathered by the world collector.")
        if not self.world_collector.instances_dict:
            self.export_world_check.setChecked(False)
            self.export_world_check.setEnabled(False)
            self.export_world_check.setToolTip("No Geometry Nodes instances of assets found in the scene.")
        column.addWidget(self.export_world_check)

        column.addSpacing(8)
        column.addWidget(QLabel("Assets:"))
        self.assets_checkboxes = []
        for item in self.asset_collector.items:
            asset_checkbox = QCheckBox(item.name)
            asset_checkbox.setChecked(True)
            asset_checkbox.toggled.connect(self._refresh_layer_checks)
            self.assets_checkboxes.append(asset_checkbox)
            column.addWidget(asset_checkbox)
        if not self.assets_checkboxes:
            column.addWidget(QLabel("No assets found."))
        return group

    def _build_layers_group(self):
        """which data layers each asset gets"""
        group = QGroupBox("Asset layers")
        column = QVBoxLayout(group)
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
            column.addWidget(check)

        # check -> (asset data property, tooltip name), geometry first because physics needs it
        self.layer_data_checks = {
            self.geometry_check: ("has_geometry", "meshes"),
            self.materials_check: ("has_materials", "materials"),
            self.armature_check: ("has_armature", "armature"),
            self.physics_check: ("has_physics", "rigid bodies"),
        }
        # user's choice, restored when a disabled check is enabled again
        self._remembered_checks = {}
        self._refreshing_checks = False
        self.geometry_check.toggled.connect(self._refresh_layer_checks)
        return group

    def _refresh_layer_checks(self, *_):
        """disable layer checks that no selected asset has data for"""
        # unchecking Geometry calls this method again
        if self._refreshing_checks:
            return
        self._refreshing_checks = True
        try:
            selected_names = {check.text() for check in self.assets_checkboxes if check.isChecked()}
            selected_items = [item for item in self.asset_collector.items if item.name in selected_names]

            for check, (data_attr, data_label) in self.layer_data_checks.items():
                available = any(getattr(item, data_attr) for item in selected_items)
                reason = f"No {data_label} in the selected assets."
                if check is self.physics_check and available and not self.geometry_check.isChecked():
                    available = False
                    reason = "Physics needs Geometry."
                self._set_check_available(check, available, reason)

            # proxies are part of geometry
            self.proxy_group.setEnabled(self.geometry_check.isChecked())
        finally:
            self._refreshing_checks = False

    def _set_check_available(self, check, available, reason):
        if available:
            if not check.isEnabled():
                check.setEnabled(True)
                check.setChecked(self._remembered_checks.pop(check, True))
            check.setToolTip("")
        else:
            if check.isEnabled():
                self._remembered_checks[check] = check.isChecked()
                check.setChecked(False)
                check.setEnabled(False)
            check.setToolTip(reason)

    def _build_stage_group(self):
        """stage metadata and unit conversion"""
        group = QGroupBox("Stage")
        form = QFormLayout(group)

        self.up_axis_combo = QComboBox()
        self.up_axis_combo.addItems(["z", "y"])
        form.addRow("Up axis", self.up_axis_combo)

        # authored as the stage's metersPerUnit
        self.meter_per_unit = QLineEdit()
        self.meter_per_unit.setValidator(self._create_double_validator(0.0001, 1000))
        self.meter_per_unit.setText("1.0")
        self.meter_per_unit.setToolTip("Written as the stage's metersPerUnit metadata.")
        form.addRow("Meters per unit", self.meter_per_unit)

        self.mesh_scale = QLineEdit()
        self.mesh_scale.setValidator(self._create_double_validator(0.0001, 1000))
        self.mesh_scale.setText("1.0")
        self.mesh_scale.setToolTip("Multiplier applied to points and translations on export.")
        form.addRow("Mesh scale", self.mesh_scale)
        return group

    def _build_proxy_group(self):
        """automatic decimated proxy LOD"""
        group = QGroupBox("Proxy LOD")
        self.proxy_group = group
        form = QFormLayout(group)

        self.proxy_generator_check = QCheckBox("Generate proxy LOD")
        self.proxy_generator_check.setChecked(True)
        form.addRow(self.proxy_generator_check)

        decimate_ratio_lay = QHBoxLayout()
        self.decimate_slider = FloatSlider()
        self.decimate_slider.set_value_float(0.025)
        self.ratio_txt = QLineEdit("0.025")
        self.ratio_txt.setValidator(self._create_double_validator(0.00001, 1.0))
        self.ratio_txt.setFixedWidth(100)
        self.ratio_txt.editingFinished.connect(self._sync_ratio_slider)
        self.decimate_slider.floatValueChanged.connect(self._sync_slider_to_text)
        decimate_ratio_lay.addWidget(self.decimate_slider)
        decimate_ratio_lay.addWidget(self.ratio_txt)
        form.addRow("Decimate ratio", decimate_ratio_lay)

        # the ratio is meaningless without proxy generation
        def _toggle_ratio(enabled):
            self.decimate_slider.setEnabled(enabled)
            self.ratio_txt.setEnabled(enabled)
        self.proxy_generator_check.toggled.connect(_toggle_ratio)
        return group

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
        
        logger.info(f"Exporting USD layers to: {self.output_dir_edit.text()}")
        usd_exporter = UsdExporter(settings)
        
        # exporting assets
        asset_items = settings["collected_assets_item"]
        for asset_item in asset_items:
            logger.info(f"Exporting asset: {asset_item.name}")
            proxy_generator = None
            if settings["generate_proxy"]:
                decimate_ratio = settings["decimate_ratio"]
                proxy_generator = ProxyGenerator(asset_item, decimate_ratio)
                proxy_generator.add_proxy()
            usd_exporter.export_assets(asset_item)
            if proxy_generator:
                proxy_generator.clear()

        # exporting world collection
        usd_exporter.export_world()

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
        collected_assets_items = [x for x in self.asset_collector.items if x.name in selected_assets_names]
        collected_world_dict = self.world_collector.instances_dict if self.export_world_check.isChecked() else None
        output_dir = os.path.normpath(os.path.expanduser(self.output_dir_edit.text().strip()))
        return {
            "projects_root": os.path.dirname(output_dir),
            "project_name": os.path.basename(output_dir),
            "sublayer_resolver": self.sublayer_resolver_combo.currentText(),
            "extension": self.extension_combo.currentText(),
            "export_world": self.export_world_check.isChecked(),
            "export_geometry": self.geometry_check.isChecked(),
            "export_materials": self.materials_check.isChecked(),
            "export_armature": self.armature_check.isChecked(),
            "export_physics": self.physics_check.isChecked(),
            "export_world": self.export_world_check.isChecked(),
            "up_axis": self.up_axis_combo.currentText(),
            "collected_assets_item": collected_assets_items,
            "collected_world_item": collected_world_dict,
            "meter_per_unit": float(self.meter_per_unit.text()),
            "mesh_scale": float(self.mesh_scale.text()),
            "generate_proxy": self.proxy_generator_check.isChecked() and self.geometry_check.isChecked(),
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
"""
collision_hull_gui.py

PySide6 front-end for ``collision_hull.CollisionHullBuilder``.

Usage inside Blender (Text Editor "Run Script" or the Python console):

    import collision_hull_gui
    collision_hull_gui.show()

One-time setup: Blender does not ship PySide6, install it into Blender's own
Python, e.g.

    <blender>/<version>/python/bin/python3.11 -m pip install PySide6

``collision_hull.py`` must be importable (same folder on sys.path, or a text
block named ``collision_hull.py`` in the open .blend).

Event loop: ``QApplication.exec()`` would freeze Blender, so a
``bpy.app.timers`` callback calls ``processEvents()`` while the window is open.
That keeps every button handler on Blender's main thread, which is required
for touching ``bpy.data``.
"""
from __future__ import annotations

import math
import traceback
from typing import Optional

import bpy
from PySide6 import QtCore, QtWidgets

from convex_hull_generator.collision_hull import COLLISION_SUFFIX, CollisionHullBuilder, ConvexHullParams

__all__ = ["CollisionHullWindow", "show"]

_PUMP_INTERVAL = 0.02  # seconds between Qt event passes


class CollisionHullWindow(QtWidgets.QWidget):
    """Pick mesh objects, tweak hull parameters, press Generate."""

    def __init__(
        self,
        builder: Optional[CollisionHullBuilder] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self._builder = builder or CollisionHullBuilder()
        self.setWindowTitle("Collision Hull Generator")
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.resize(380, 540)
        self._build_ui()
        self._on_defaults_toggled(self._defaults_cb.isChecked())

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        defaults = ConvexHullParams()
        root = QtWidgets.QVBoxLayout(self)

        # Sources
        src_box = QtWidgets.QGroupBox("Source meshes")
        src_lay = QtWidgets.QVBoxLayout(src_box)
        self._list = QtWidgets.QListWidget()
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        src_lay.addWidget(self._list)

        row = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Add selected")
        remove_btn = QtWidgets.QPushButton("Remove")
        clear_btn = QtWidgets.QPushButton("Clear")
        add_btn.clicked.connect(self._add_selected)
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn.clicked.connect(self._list.clear)
        for b in (add_btn, remove_btn, clear_btn):
            row.addWidget(b)
        src_lay.addLayout(row)
        root.addWidget(src_box, stretch=1)

        # Hull parameters
        par_box = QtWidgets.QGroupBox("Convex hull parameters")
        par_lay = QtWidgets.QFormLayout(par_box)

        self._defaults_cb = QtWidgets.QCheckBox("Use standard parameters")
        self._defaults_cb.setChecked(True)
        self._defaults_cb.toggled.connect(self._on_defaults_toggled)
        par_lay.addRow(self._defaults_cb)

        self._merge = QtWidgets.QDoubleSpinBox()
        self._merge.setDecimals(6)
        self._merge.setRange(0.0, 1.0)
        self._merge.setSingleStep(1e-4)
        self._merge.setSpecialValueText("Off")
        self._merge.setValue(defaults.merge_distance)
        par_lay.addRow("Merge distance", self._merge)

        self._angle = QtWidgets.QDoubleSpinBox()
        self._angle.setDecimals(2)
        self._angle.setRange(0.0, 90.0)
        self._angle.setSingleStep(0.5)
        self._angle.setSuffix("°")
        self._angle.setSpecialValueText("Off")
        self._angle.setValue(math.degrees(defaults.dissolve_angle))
        par_lay.addRow("Dissolve angle", self._angle)

        self._max_verts = QtWidgets.QSpinBox()
        self._max_verts.setRange(0, 100000)
        self._max_verts.setSpecialValueText("Off")
        self._max_verts.setValue(defaults.max_vertices or 0)
        par_lay.addRow("Max vertices (warn)", self._max_verts)
        root.addWidget(par_box)

        # Output options
        out_box = QtWidgets.QGroupBox("Output")
        out_lay = QtWidgets.QFormLayout(out_box)
        self._name_edit = QtWidgets.QLineEdit()
        self._name_edit.setPlaceholderText(f"<first object>{COLLISION_SUFFIX}")
        out_lay.addRow("Name", self._name_edit)
        self._parent_cb = QtWidgets.QCheckBox("Parent source objects to collision mesh")
        out_lay.addRow(self._parent_cb)
        root.addWidget(out_box)

        # Generate + status
        self._generate_btn = QtWidgets.QPushButton("Generate")
        self._generate_btn.setMinimumHeight(32)
        self._generate_btn.clicked.connect(self._generate)
        root.addWidget(self._generate_btn)

        self._status = QtWidgets.QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

    # ------------------------------------------------------------- helpers
    def _names(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status.setStyleSheet("color: #c0392b;" if error else "")
        self._status.setText(text)

    def _params(self) -> Optional[ConvexHullParams]:
        """None means: let the builder use its standard parameters."""
        if self._defaults_cb.isChecked():
            return None
        return ConvexHullParams(
            merge_distance=self._merge.value(),
            dissolve_angle=math.radians(self._angle.value()),
            max_vertices=self._max_verts.value() or None,
        )

    # ------------------------------------------------------------ handlers
    def _on_defaults_toggled(self, use_defaults: bool) -> None:
        for w in (self._merge, self._angle, self._max_verts):
            w.setEnabled(not use_defaults)

    def _add_selected(self) -> None:
        known = set(self._names())
        added = 0
        for obj in bpy.context.view_layer.objects:
            if (
                obj.type == "MESH"
                and obj.select_get()
                and not obj.name.endswith(COLLISION_SUFFIX)
                and obj.name not in known
            ):
                self._list.addItem(obj.name)
                known.add(obj.name)
                added += 1
        if added == 0:
            self._set_status("No new selected mesh objects found.", error=True)
        else:
            self._set_status(f"Added {added} object(s).")

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    def _generate(self) -> None:
        # Resolve names at click time; objects may have been renamed or deleted.
        objs, missing = [], []
        for name in self._names():
            obj = bpy.data.objects.get(name)
            (objs if obj is not None else missing).append(obj if obj else name)
        if not objs:
            self._set_status("Add at least one mesh object.", error=True)
            return

        try:
            result = self._builder.generate(
                objs,
                hull_params=self._params(),
                parent_to_final=self._parent_cb.isChecked(),
                name=self._name_edit.text().strip() or None,
            )
        except Exception as exc:  # show it in the UI, full trace in the console
            traceback.print_exc()
            self._set_status(f"Failed: {exc}", error=True)
            return

        mesh = result.data
        msg = (
            f"Created {result.name}: "
            f"{len(mesh.vertices)} verts, {len(mesh.polygons)} faces"
        )
        if missing:
            msg += f"\nSkipped (not found): {', '.join(missing)}"
        self._set_status(msg)


# ------------------------------------------------------------ Blender glue
_window: Optional[CollisionHullWindow] = None


def _pump() -> Optional[float]:
    """bpy.app.timers callback: run Qt events; stop when the window is gone."""
    app = QtWidgets.QApplication.instance()
    if app is None or _window is None or not _window.isVisible():
        return None  # unregisters the timer
    app.processEvents()
    return _PUMP_INTERVAL


def show(builder: Optional[CollisionHullBuilder] = None) -> CollisionHullWindow:
    """Open the window (replacing an already open one) and return it."""
    global _window
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["blender"])
    app.setQuitOnLastWindowClosed(False)

    if _window is not None:
        _window.close()
    _window = CollisionHullWindow(builder)
    _window.show()
    _window.raise_()

    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.0)
    return _window


if __name__ == "__main__":
    show()
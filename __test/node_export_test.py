import subprocess
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLEND_FILE = PROJECT_ROOT / "__sample_blend_files" / "test_robot" / "robotic_arm_v001.blend"
EXPORT_FLAG = "--monke-export"


def launch_blender():
    sys.path.insert(0, str(PROJECT_ROOT))
    from pipeline_config import load_pipeline_env
    from run_blender import get_pipeline_env

    env = load_pipeline_env()
    pipeline_env = get_pipeline_env(env)
    # no display in background mode, Qt has to render offscreen
    pipeline_env["QT_QPA_PLATFORM"] = "offscreen"
    pipeline_env["MONKE_SITE_PACKAGES"] = env["MONKE_SITE_PACKAGES"]

    command = ["flatpak", "run"]
    for name, value in pipeline_env.items():
        command.append(f"--env={name}={value}")
    command.append(env["BLENDER_FLATPAK_APP_ID"])
    command += ["--background", str(BLEND_FILE), "--python-exit-code", "1", "--python", __file__, "--", EXPORT_FLAG]

    result = subprocess.run(command)
    sys.exit(result.returncode)


def run_export():
    import os
    import bpy

    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.append(os.environ["MONKE_SITE_PACKAGES"])

    from publisher_plugin import register
    register()

    from PySide6.QtWidgets import QApplication
    from ui.blender_publisher_ui import MonkeUsdExportDialog

    app = QApplication.instance() or QApplication([])
    dialog = MonkeUsdExportDialog()
    app.processEvents()

    output_nodes = [node for node in dialog.node_graph.all_nodes() if node.__identifier__ == "nodes.output"]
    print(f"[node_export_test] blend file: {bpy.data.filepath}")
    print(f"[node_export_test] output nodes: {len(output_nodes)}")
    for node in output_nodes:
        print(f"[node_export_test]   {node.name()} -> {node.get_property('output_path')}")

    dialog.export()
    app.processEvents()
    print("[node_export_test] export finished")
    # TODO check the output files with pxr


if __name__ == "__main__":
    if EXPORT_FLAG in sys.argv:
        run_export()
    else:
        launch_blender()

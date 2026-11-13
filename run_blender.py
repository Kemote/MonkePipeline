import subprocess
import tempfile
import textwrap

from pathlib import Path

from pipeline_config import PROJECT_ROOT, load_pipeline_env


def get_pipeline_env(env):
    pipeline_env = {
        "MONKENAME": env["MONKENAME"],
        "LD_LIBRARY_PATH": env["LD_LIBRARY_PATH"],
        "PXR_PLUGINPATH_NAME": env["PXR_PLUGINPATH_NAME_BLENDER"],
    }
    # project vars are optional: when left empty the exporter falls back
    # to a "<blend name>_usd" folder next to the .blend file
    for name in ("PROJECTSROOT", "PROJECTNAME"):
        value = env.get(name, "").strip()
        if value:
            pipeline_env[name] = value
    return pipeline_env


def write_bootstrap_script(pyside6_site_packages):
    script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(PROJECT_ROOT)!r})
        sys.path.append({pyside6_site_packages!r})

        from publisher_plugin import register
        register()
    """)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="monke_bootstrap_", delete=False,
        dir=str(PROJECT_ROOT),
    )
    tmp.write(script)
    tmp.close()
    return Path(tmp.name)


def run_blender():
    env = load_pipeline_env()
    bootstrap_script = write_bootstrap_script(env["PYSIDE6_SITE_PACKAGES"])
    command = ["flatpak", "run"]
    if env.get("QT_QPA_PLATFORM") == "xcb":
        # Wayland ignores Qt.WindowStaysOnTopHint, so run Qt through XWayland.
        # The Blender Flatpak only has fallback-x11, which hides the X11
        # socket on Wayland sessions, so expose it explicitly.
        command.append("--socket=x11")
        command.append("--env=QT_QPA_PLATFORM=xcb")
    for name, value in get_pipeline_env(env).items():
        command.append(f"--env={name}={value}")
    command.append(env["BLENDER_FLATPAK_APP_ID"])
    command += ["--python", str(bootstrap_script)]

    try:
        subprocess.run(command)
    finally:
        bootstrap_script.unlink(missing_ok=True)


if __name__ == "__main__":
    run_blender()

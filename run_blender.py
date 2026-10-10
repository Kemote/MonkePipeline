import subprocess
import tempfile
import textwrap

from pathlib import Path

from pipeline_config import PROJECT_ROOT, load_pipeline_env


def get_pipeline_env(env):
    return {
        "MONKENAME": env["MONKENAME"],
        "LD_LIBRARY_PATH": env["LD_LIBRARY_PATH"],
        "PROJECTNAME": env["PROJECTNAME"],
        "PXR_PLUGINPATH_NAME": env["PXR_PLUGINPATH_NAME_BLENDER"],
        "QT_QPA_PLATFORM": env["QT_QPA_PLATFORM"],
    }


def write_bootstrap_script(MONKE_SITE_PACKAGES):
    script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(PROJECT_ROOT)!r})
        sys.path.append({MONKE_SITE_PACKAGES!r})

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
    bootstrap_script = write_bootstrap_script(env["MONKE_SITE_PACKAGES"])
    # flatpak only grants X11 as fallback-x11, xcb needs the socket explicitly
    command = ["flatpak", "run", "--nosocket=fallback-x11", "--socket=x11"]
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

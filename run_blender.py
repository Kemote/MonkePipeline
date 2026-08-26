import subprocess
import tempfile
import textwrap

from pathlib import Path


PROJECT_ROOT = Path("/home/kemot/Documents/Dev/MonkePipeline")
BLENDER_FLATPAK_APP_ID = "org.blender.Blender"
PYSIDE6_SITE_PACKAGES = Path("/home/kemot/Documents/Dev/_VENVS/python-usd-venv/lib/python3.12/site-packages")


def get_pipeline_env():
    return {
        "LD_LIBRARY_PATH": "/home/kemot/USD/lib",
        "PROJECTNAME": "sample_usd_files",
        "PXR_PLUGINPATH_NAME": str(PROJECT_ROOT / "usd_asset_resolver" / "build"),
    }


def write_bootstrap_script():
    script = textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(PROJECT_ROOT)!r})
        sys.path.append({str(PYSIDE6_SITE_PACKAGES)!r})

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
    bootstrap_script = write_bootstrap_script()
    command = ["flatpak", "run"]
    for name, value in get_pipeline_env().items():
        command.append(f"--env={name}={value}")
    command.append(BLENDER_FLATPAK_APP_ID)
    command += ["--python", str(bootstrap_script)]

    try:
        subprocess.run(command)
    finally:
        bootstrap_script.unlink(missing_ok=True)


if __name__ == "__main__":
    run_blender()

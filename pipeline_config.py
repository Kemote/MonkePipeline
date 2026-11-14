import os

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / "pipeline.env"
ENV_FILE_EXAMPLE = PROJECT_ROOT / "pipeline.env.example"


def load_pipeline_env(env_file=None):
    """
    parse the KEY=VALUE pipeline.env file into a dict.
    Load envs from provided file path
    """
    path = Path(env_file) if env_file else ENV_FILE
    if not path.exists():
        path = ENV_FILE_EXAMPLE

    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key.strip()] = value
    return env


def apply_pipeline_env(env_file=None):
    for key, value in load_pipeline_env(env_file).items():
        os.environ.setdefault(key, value)


def resolve_project_location(blend_filepath):
    """
    return (projects_root, project_name, from_env) for the export output.

    PROJECTSROOT / PROJECTNAME from the environment win (empty counts as unset).
    Each missing one falls back to the .blend file: root = its folder,
    name = "<blend stem>_usd", so the output sits next to the .blend.
    For an unsaved .blend (empty path) a missing value is returned as None.
    from_env is True when PROJECTSROOT is set - the project then owns the location.
    """
    projects_root = os.environ.get("PROJECTSROOT", "").strip() or None
    project_name = os.environ.get("PROJECTNAME", "").strip() or None
    from_env = projects_root is not None

    if blend_filepath:
        blend_path = Path(blend_filepath)
        projects_root = projects_root or str(blend_path.parent)
        project_name = project_name or f"{blend_path.stem}_usd"

    return projects_root, project_name, from_env

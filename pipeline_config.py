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

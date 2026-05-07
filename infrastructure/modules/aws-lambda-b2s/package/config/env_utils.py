import os

from dotenv import load_dotenv


def load_env() -> str:
    env_path = os.getenv("ENV_PATH") or os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path)
    return env_path

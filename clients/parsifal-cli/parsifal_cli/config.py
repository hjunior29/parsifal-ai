"""Where the CLI finds the server URL and token: flags > environment > profile in the config file."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

DEFAULT_URL = "http://localhost:8000"
ENV_URL, ENV_TOKEN, ENV_PROFILE, ENV_CONFIG = "PARSIFAL_URL", "PARSIFAL_TOKEN", "PARSIFAL_PROFILE", "PARSIFAL_CONFIG"


def config_path():
    if os.environ.get(ENV_CONFIG):
        return Path(os.environ[ENV_CONFIG])
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "parsifal" / "config.toml"


def load_profiles(path=None):
    path = path or config_path()
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def save_profiles(profiles, path=None):
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, values in profiles.items():
        lines.append(f"[{name}]")
        for key, value in values.items():
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        lines.append("")
    path.write_text("\n".join(lines))
    try:
        path.chmod(0o600)  # the file holds tokens
    except OSError:  # pragma: no cover
        pass


@dataclass
class Settings:
    url: str = DEFAULT_URL
    token: str | None = None
    profile: str = "default"

    @property
    def api_base(self):
        return self.url.rstrip("/") + "/api/v1"


def resolve(url=None, token=None, profile=None):
    """Combine explicit values, environment variables and the config file into Settings."""
    profile = profile or os.environ.get(ENV_PROFILE) or "default"
    stored = load_profiles().get(profile, {})
    return Settings(
        url=url or os.environ.get(ENV_URL) or stored.get("url") or DEFAULT_URL,
        token=token or os.environ.get(ENV_TOKEN) or stored.get("token"),
        profile=profile,
    )


def mask(token):
    if not token:
        return None
    return token[:12] + "…" if len(token) > 12 else "…"

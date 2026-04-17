import json
import os
import sys
import threading
from pathlib import Path
from typing import Any


APP_NAME = "cancerstudio"

_settings_lock = threading.Lock()


def _load_local_env_file() -> None:
    """Load ``.env`` at the repo root into ``os.environ`` on first import.

    Without this hook the desktop app (``npm run desktop:dev``) launches
    uvicorn in a fresh subshell that doesn't inherit the user's shell
    overrides — in particular ``CANCERSTUDIO_APP_DATA_DIR`` — so the UI
    ends up pointing at the default data root and the user's real
    workspaces don't show up.

    Skipped when pytest is loaded so tests never pick up a developer's
    local ``.env`` (which would point at the production data directory
    and make the DB-cleaning fixtures destructive).

    ``os.environ.setdefault`` semantics: values already set in the
    environment (by the shell or a wrapper script) always win over
    ``.env``.
    """
    if "pytest" in sys.modules:
        return
    env_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # Strip surrounding quotes if symmetric.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_local_env_file()


def _default_app_data_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def get_app_data_root() -> Path:
    configured = (
        os.getenv("CANCERSTUDIO_APP_DATA_DIR")
        or os.getenv("APP_DATA_ROOT")
        or os.getenv("LOCAL_APP_DATA_DIR")
    )
    root = Path(configured).expanduser() if configured else _default_app_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def get_workspace_root(workspace_id: str) -> Path:
    root = get_app_data_root() / "workspaces" / workspace_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_batch_root(workspace_id: str, batch_id: str) -> Path:
    root = get_workspace_root(workspace_id) / "batches" / batch_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_batch_canonical_root(workspace_id: str, batch_id: str) -> Path:
    root = get_batch_root(workspace_id, batch_id) / "canonical"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_alignment_run_root(workspace_id: str, run_id: str) -> Path:
    root = get_workspace_root(workspace_id) / "alignment" / run_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_variant_calling_run_root(workspace_id: str, run_id: str) -> Path:
    root = get_workspace_root(workspace_id) / "variant-calling" / run_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_reference_bundle_root() -> Path:
    configured = os.getenv("REFERENCE_BUNDLE_ROOT")
    root = Path(configured).expanduser() if configured else get_app_data_root() / "references"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def get_inbox_root() -> Path:
    """Return the inbox directory users drop FASTQ/BAM/CRAM files into.

    Bind-mounted at ``/inbox`` inside the container; configurable via
    ``CANCERSTUDIO_INBOX_DIR`` for dev setups that run the backend natively.
    """
    configured = os.getenv("CANCERSTUDIO_INBOX_DIR")
    root = Path(configured).expanduser() if configured else get_app_data_root() / "inbox"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def get_local_sqlite_path() -> Path:
    configured = os.getenv("LOCAL_SQLITE_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
    else:
        path = get_app_data_root() / "app.db"

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_path_within_app_data(path: Path) -> bool:
    try:
        path.resolve().relative_to(get_app_data_root())
        return True
    except ValueError:
        return False


_APP_DATA_SUBDIRS = ("workspaces", "references", "inbox", "batches")


def resolve_app_data_path(stored: str | Path) -> Path:
    """Map a stored absolute path back into the current app-data tree.

    Catches the bind-mount/native-install path mismatch: a SQLite row created
    when the backend ran natively (paths like
    ``/media/.../cancerstudio/workspaces/.../tumor.bam``) is now read inside
    the container, where the same data lives under ``/app-data/workspaces/...``.

    If the stored path already exists on disk, it is returned untouched.
    Otherwise we look for the first known subdirectory prefix (``workspaces``,
    ``references``, ``inbox``, ``batches``) in the path's segments and rebase
    everything from that segment onward under the current app-data root. If
    no known prefix appears we return the original path so the caller's
    "missing file" error path still fires.
    """
    candidate = Path(stored)
    if candidate.exists():
        return candidate
    parts = candidate.parts
    for index, segment in enumerate(parts):
        if segment in _APP_DATA_SUBDIRS:
            rebased = get_app_data_root().joinpath(*parts[index:])
            if rebased.exists():
                return rebased
            # Return the rebased path even if missing — its absence is more
            # actionable than the original "host path not visible inside
            # container" error.
            return rebased
    return candidate


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON to path via a tmp file + rename.

    Durability note: readers that see the final path always see a complete
    document; partial writes never become visible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
    tmp_path.replace(path)


def atomic_read_json(path: Path) -> Any | None:
    """Read JSON, returning None if missing or malformed."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None


def _settings_path() -> Path:
    return get_app_data_root() / "settings.json"


def _read_settings_file() -> dict[str, Any]:
    path = _settings_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_runtime_setting(key: str) -> Any | None:
    with _settings_lock:
        return _read_settings_file().get(key)


def load_runtime_settings() -> dict[str, Any]:
    with _settings_lock:
        return dict(_read_settings_file())


def save_runtime_settings(updates: dict[str, Any], *, reset: bool = False) -> dict[str, Any]:
    with _settings_lock:
        current: dict[str, Any] = {} if reset else _read_settings_file()
        for key, value in updates.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2, sort_keys=True)
        tmp_path.replace(path)
        return dict(current)

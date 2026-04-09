from pathlib import Path
import os

from app.db import init_db
from app.services.legacy_import import import_legacy_workspace_manifests


def main() -> None:
    init_db()
    root = Path(
        os.getenv(
            "LEGACY_WORKSPACE_STORAGE_DIR",
            Path(__file__).resolve().parents[1] / "data" / "workspaces",
        )
    )
    imported = import_legacy_workspace_manifests(root)
    print(f"Imported {imported} legacy workspace manifest(s) from {root}")


if __name__ == "__main__":
    main()

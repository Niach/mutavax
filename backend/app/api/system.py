import os
import shutil

from fastapi import APIRouter

from app.runtime import get_app_data_root
from app.services.tool_preflight import (
    STROBEALIGN_INDEX_MEMORY_BYTES,
    read_available_memory_bytes,
    read_total_memory_bytes,
)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/memory")
async def get_system_memory() -> dict[str, int | None]:
    return {
        "available_bytes": read_available_memory_bytes(),
        "total_bytes": read_total_memory_bytes(),
        "threshold_bytes": STROBEALIGN_INDEX_MEMORY_BYTES,
    }


@router.get("/resources")
async def get_system_resources() -> dict[str, object]:
    app_data_root = get_app_data_root()
    try:
        usage = shutil.disk_usage(app_data_root)
        disk_total: int | None = usage.total
        disk_free: int | None = usage.free
    except OSError:
        disk_total = None
        disk_free = None
    return {
        "cpu_count": os.cpu_count() or 1,
        "total_memory_bytes": read_total_memory_bytes(),
        "available_memory_bytes": read_available_memory_bytes(),
        "app_data_disk_total_bytes": disk_total,
        "app_data_disk_free_bytes": disk_free,
        "app_data_root": str(app_data_root),
    }

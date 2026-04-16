import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.runtime import load_runtime_settings, save_runtime_settings


router = APIRouter(prefix="/api/settings", tags=["settings"])


_MEMORY_PATTERN = re.compile(r"^\d+[KMGT]?$")
_KNOWN_KEYS = {
    "aligner_threads",
    "samtools_threads",
    "samtools_sort_threads",
    "samtools_sort_memory",
    "chunk_reads",
    "chunk_parallelism",
}


class AlignmentSettingsDefaults(BaseModel):
    aligner_threads: int
    samtools_threads: int
    samtools_sort_threads: int
    samtools_sort_memory: str
    chunk_reads: int
    chunk_parallelism: int


class AlignmentSettingsResponse(AlignmentSettingsDefaults):
    defaults: AlignmentSettingsDefaults


class AlignmentSettingsPatch(BaseModel):
    aligner_threads: Optional[int] = Field(default=None, ge=1, le=256)
    samtools_threads: Optional[int] = Field(default=None, ge=1, le=256)
    samtools_sort_threads: Optional[int] = Field(default=None, ge=1, le=256)
    samtools_sort_memory: Optional[str] = Field(default=None, min_length=1, max_length=16)
    chunk_reads: Optional[int] = Field(default=None, ge=1_000_000, le=500_000_000)
    chunk_parallelism: Optional[int] = Field(default=None, ge=1, le=8)
    reset: bool = False


def _compute_defaults() -> AlignmentSettingsDefaults:
    cpu_count = os.cpu_count() or 4
    return AlignmentSettingsDefaults(
        aligner_threads=max(1, cpu_count - 4),
        samtools_threads=max(1, cpu_count // 4),
        samtools_sort_threads=3,
        samtools_sort_memory="2G",
        chunk_reads=20_000_000,
        chunk_parallelism=2,
    )


def _build_response(stored: dict) -> AlignmentSettingsResponse:
    defaults = _compute_defaults()

    def _int(key: str, fallback: int) -> int:
        value = stored.get(key)
        try:
            if value is None:
                return fallback
            return max(1, int(value))
        except (TypeError, ValueError):
            return fallback

    def _str(key: str, fallback: str) -> str:
        value = stored.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    return AlignmentSettingsResponse(
        aligner_threads=_int("aligner_threads", defaults.aligner_threads),
        samtools_threads=_int("samtools_threads", defaults.samtools_threads),
        samtools_sort_threads=_int("samtools_sort_threads", defaults.samtools_sort_threads),
        samtools_sort_memory=_str("samtools_sort_memory", defaults.samtools_sort_memory),
        chunk_reads=_int("chunk_reads", defaults.chunk_reads),
        chunk_parallelism=_int("chunk_parallelism", defaults.chunk_parallelism),
        defaults=defaults,
    )


@router.get("/alignment", response_model=AlignmentSettingsResponse)
async def get_alignment_settings() -> AlignmentSettingsResponse:
    stored = {k: v for k, v in load_runtime_settings().items() if k in _KNOWN_KEYS}
    return _build_response(stored)


@router.patch("/alignment", response_model=AlignmentSettingsResponse)
async def update_alignment_settings(body: AlignmentSettingsPatch) -> AlignmentSettingsResponse:
    if body.samtools_sort_memory is not None and not _MEMORY_PATTERN.match(body.samtools_sort_memory):
        raise HTTPException(
            status_code=422,
            detail="samtools_sort_memory must match pattern like '2G', '512M', '1024K'",
        )

    updates: dict[str, object | None] = {}
    for key in _KNOWN_KEYS:
        value = getattr(body, key, None)
        if value is not None:
            updates[key] = value

    if body.reset:
        stored = save_runtime_settings({}, reset=True)
    else:
        stored = save_runtime_settings(updates)
    scoped = {k: v for k, v in stored.items() if k in _KNOWN_KEYS}
    return _build_response(scoped)

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Activity(BaseModel):
    """
    Canonical normalized activity record for schedule intelligence (Phase 14).

    Produced from the authoritative Asta Powerproject CSV export; consumed by graph,
    driver, and risk phases. Synthetic activities (unit tests) may omit ``source_row_index``.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    task_id: str = Field(description="Task ID — primary graph key")
    source_row_index: int | None = Field(
        default=None,
        description="1-based physical CSV row number (header is row 1); None for synthetic non-CSV activities",
    )
    task_name: str | None = None
    unique_task_id: str | None = None
    start: datetime | None = None
    finish: datetime | None = None
    duration_days: float | None = None
    duration_remaining_days: float | None = None
    early_start: datetime | None = None
    early_finish: datetime | None = None
    late_start: datetime | None = None
    late_finish: datetime | None = None
    total_float_days: float | None = None
    free_float_days: float | None = None
    critical: bool | None = None
    predecessors: list[str] | None = None
    successors: list[str] | None = None
    critical_path_drag_days: float | None = None
    phase_exec: str | None = None
    control_account: str | None = None
    area_zone: str | None = None
    level: str | None = None
    csi: str | None = None
    system: str | None = None
    percent_complete: float | None = None
    original_start: datetime | None = None
    original_finish: datetime | None = None

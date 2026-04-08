"""
Deterministic normalized intake document for Asta CSV (Phase 14).

Emitted as ``normalized_intake.json`` alongside other schedule intelligence artifacts.
"""

from __future__ import annotations

from typing import Any

from .models import Activity

NORMALIZED_INTAKE_SCHEMA_VERSION = "asta_normalized_intake_v1"


def build_normalized_intake_payload(
    activities: list[Activity],
    *,
    warnings: tuple[str, ...],
    source_display_name: str,
    source_sha256_hex: str | None,
) -> dict[str, Any]:
    """
    Build a JSON-serializable, stable-order document for export.

    Activities are sorted by ``source_row_index`` (then ``task_id``) so identical inputs
    produce byte-identical JSON when combined with stable JSON settings.
    """
    acts_sorted = sorted(
        activities,
        key=lambda a: (
            a.source_row_index if a.source_row_index is not None else 1_000_000_000,
            a.task_id,
        ),
    )
    return {
        "schema_version": NORMALIZED_INTAKE_SCHEMA_VERSION,
        "source_csv": source_display_name,
        "source_sha256": source_sha256_hex,
        "activity_count": len(activities),
        "intake_warnings": list(warnings),
        "activities": [a.model_dump(mode="json") for a in acts_sorted],
    }

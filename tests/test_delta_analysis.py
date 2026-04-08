from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from controltower.schedule_intake import Activity, compare_schedule_csv_paths, compare_schedule_exports

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "asta_export_authoritative_fixture.csv"


def test_identical_activities_empty_delta() -> None:
    acts = [
        Activity(task_id="1", finish=datetime(2026, 1, 1), successors=["2"]),
        Activity(task_id="2", predecessors=["1"]),
    ]
    r = compare_schedule_exports(acts, list(acts))
    assert r.added_task_ids == ()
    assert r.removed_task_ids == ()
    assert r.summary_counts.changed_finish_dates == 0
    assert r.summary_counts.logic_edges_added == 0
    assert r.summary_counts.logic_edges_removed == 0


def test_added_removed_tasks() -> None:
    b = [Activity(task_id="a"), Activity(task_id="b")]
    c = [Activity(task_id="b"), Activity(task_id="c")]
    r = compare_schedule_exports(b, c)
    assert r.added_task_ids == ("c",)
    assert r.removed_task_ids == ("a",)
    assert r.baseline_task_count == 2
    assert r.current_task_count == 2


def test_finish_change_detected() -> None:
    b = [Activity(task_id="x", finish=datetime(2026, 1, 1))]
    c = [Activity(task_id="x", finish=datetime(2026, 2, 1))]
    r = compare_schedule_exports(b, c)
    assert len(r.changed_finish_dates) == 1
    assert r.changed_finish_dates[0].task_id == "x"
    assert "2026-01-01" in r.changed_finish_dates[0].old_value
    assert "2026-02-01" in r.changed_finish_dates[0].new_value


def test_predecessor_set_change() -> None:
    b = [Activity(task_id="t", predecessors=["1", "2"])]
    c = [Activity(task_id="t", predecessors=["2", "3"])]
    r = compare_schedule_exports(b, c)
    assert len(r.changed_predecessors) == 1
    d = r.changed_predecessors[0]
    assert d.tokens_removed == ("1",)
    assert d.tokens_added == ("3",)


def test_logic_edges_added_removed() -> None:
    b = [
        Activity(task_id="1", successors=["2"]),
        Activity(task_id="2", predecessors=["1"]),
    ]
    c = [
        Activity(task_id="1", successors=["2", "3"]),
        Activity(task_id="2", predecessors=["1"]),
        Activity(task_id="3", predecessors=["1"]),
    ]
    r = compare_schedule_exports(b, c)
    assert ("1", "3") in r.logic_edges_added
    assert r.summary_counts.logic_edges_added == 1
    assert r.summary_counts.logic_edges_removed == 0


def test_deterministic_ordering_field_changes() -> None:
    b = [
        Activity(task_id="b", finish=datetime(2026, 1, 2)),
        Activity(task_id="a", finish=datetime(2026, 1, 1)),
    ]
    c = [
        Activity(task_id="b", finish=datetime(2026, 1, 3)),
        Activity(task_id="a", finish=datetime(2026, 1, 4)),
    ]
    r = compare_schedule_exports(b, c)
    ids = [x.task_id for x in r.changed_finish_dates]
    assert ids == sorted(ids)


def test_same_fixture_twice_no_changes() -> None:
    assert FIXTURE.is_file()
    r = compare_schedule_csv_paths(FIXTURE, FIXTURE)
    assert r.summary_counts.added_tasks == 0
    assert r.summary_counts.removed_tasks == 0
    assert r.summary_counts.changed_finish_dates == 0
    assert r.summary_counts.driver_rank_changes == 0


def test_driver_rank_delta_when_critical_changes() -> None:
    b = [
        Activity(task_id="u", total_float_days=0.0, critical=False),
        Activity(task_id="v", total_float_days=0.0, critical=True),
    ]
    c = [
        Activity(task_id="u", total_float_days=0.0, critical=True),
        Activity(task_id="v", total_float_days=0.0, critical=False),
    ]
    r = compare_schedule_exports(b, c)
    assert r.summary_counts.driver_rank_changes >= 1
    tids = {d.task_id for d in r.driver_rank_deltas}
    assert "u" in tids or "v" in tids


@pytest.mark.skipif(not FIXTURE.is_file(), reason="fixture missing")
def test_csv_roundtrip_fixture(tmp_path: Path) -> None:
    """Copy fixture to two paths; tweak finish on one row in current."""
    import csv
    import shutil

    base = tmp_path / "base.csv"
    cur = tmp_path / "cur.csv"
    shutil.copy(FIXTURE, base)
    shutil.copy(FIXTURE, cur)
    with cur.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    fi = header.index("Finish")
    for i, row in enumerate(rows[1:], start=1):
        if row and row[0] == "101":
            row[fi] = "12/31/2026"
            rows[i] = row
            break
    with cur.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    r = compare_schedule_csv_paths(base, cur)
    assert any(x.task_id == "101" for x in r.changed_finish_dates)

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pytest

from controltower.schedule_intake import AstaIntakeError, parse_asta_export_csv
from controltower.schedule_intake.asta_csv import ASTA_EXPORT_HEADERS

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "asta_export_authoritative_fixture.csv"


def _write_temp_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    import csv

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS), lineterminator="\n")
    writer.writeheader()
    for r in rows:
        full = {h: r.get(h, "") for h in ASTA_EXPORT_HEADERS}
        writer.writerow(full)
    p = tmp_path / "sample.csv"
    p.write_text(buf.getvalue(), encoding="utf-8")
    return p


def test_parse_minimal_row(tmp_path: Path) -> None:
    path = _write_temp_csv(
        tmp_path,
        [
            {
                "Task ID": "100",
                "Task name": "Pour slab",
                "Unique task ID": "U-100",
                "Duration": "5d",
                "Duration remaining": "2d",
                "Start": "4/1/2026",
                "Finish": "4/7/2026",
                "Early start": "4/1/2026",
                "Early finish": "4/7/2026",
                "Late start": "4/2/2026",
                "Late finish": "4/8/2026",
                "Total float": "1d",
                "Free float": "0d",
                "Critical": "FALSE",
                "Predecessors": "99, 98",
                "Successors": "101",
                "Critical path drag": "0d",
                "Phase Exec": "P1",
                "Control Account": "CA1",
                "Area Zone": "A",
                "Level": "L1",
                "CSI": "03",
                "System": "S1",
                "Percent complete": "40%",
                "Original start": "3/1/2026",
                "Original finish": "3/10/2026",
            }
        ],
    )
    result = parse_asta_export_csv(path)
    assert not result.warnings
    assert len(result.activities) == 1
    a = result.activities[0]
    assert a.task_id == "100"
    assert a.task_name == "Pour slab"
    assert a.unique_task_id == "U-100"
    assert a.duration_days == 5.0
    assert a.duration_remaining_days == 2.0
    assert a.start == datetime(2026, 4, 1)
    assert a.finish == datetime(2026, 4, 7)
    assert a.predecessors == ["99", "98"]
    assert a.successors == ["101"]
    assert a.critical is False
    assert a.percent_complete == 40.0
    assert a.total_float_days == 1.0
    assert a.source_row_index == 2


def test_none_and_blank_normalization(tmp_path: Path) -> None:
    path = _write_temp_csv(
        tmp_path,
        [
            {
                "Task ID": "1",
                "Task name": "<None>",
                "Unique task ID": "",
                "Duration": "<None>",
                "Duration remaining": "",
                "Start": "",
                "Finish": "<none>",
                "Early start": "",
                "Early finish": "",
                "Late start": "",
                "Late finish": "",
                "Total float": "",
                "Free float": "",
                "Critical": "",
                "Predecessors": "<None>",
                "Successors": "",
                "Critical path drag": "",
                "Phase Exec": "",
                "Control Account": "",
                "Area Zone": "",
                "Level": "",
                "CSI": "",
                "System": "",
                "Percent complete": "",
                "Original start": "",
                "Original finish": "",
            }
        ],
    )
    result = parse_asta_export_csv(path)
    a = result.activities[0]
    assert a.task_name is None
    assert a.unique_task_id is None
    assert a.duration_days is None
    assert a.predecessors is None
    assert a.successors is None
    assert result.activities[0].source_row_index == 2


def test_skip_row_without_task_id(tmp_path: Path) -> None:
    path = _write_temp_csv(
        tmp_path,
        [
            {
                "Task ID": "",
                "Task name": "orphan",
            },
            {"Task ID": "10", "Task name": "ok"},
        ],
    )
    result = parse_asta_export_csv(path)
    assert len(result.activities) == 1
    assert result.activities[0].task_id == "10"
    assert result.activities[0].source_row_index == 3
    assert any("missing Task ID" in w for w in result.warnings)


def test_malformed_date_and_duration_warnings(tmp_path: Path) -> None:
    path = _write_temp_csv(
        tmp_path,
        [
            {
                "Task ID": "20",
                "Start": "not-a-date",
                "Duration": "xyz",
            },
        ],
    )
    result = parse_asta_export_csv(path)
    assert len(result.activities) == 1
    assert result.activities[0].start is None
    assert result.activities[0].duration_days is None
    assert any("cannot parse" in w for w in result.warnings)
    assert result.activities[0].source_row_index == 2


def test_critical_true(tmp_path: Path) -> None:
    path = _write_temp_csv(tmp_path, [{"Task ID": "x", "Critical": "TRUE"}])
    a = parse_asta_export_csv(path).activities[0]
    assert a.critical is True
    assert a.source_row_index == 2


def test_missing_required_column_raises(tmp_path: Path) -> None:
    import csv

    headers = [h for h in ASTA_EXPORT_HEADERS if h != "Total float"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerow({h: ("1" if h == "Task ID" else "") for h in headers})
    p = tmp_path / "bad_header.csv"
    p.write_text(buf.getvalue(), encoding="utf-8")
    with pytest.raises(AstaIntakeError, match="Missing required column"):
        parse_asta_export_csv(p)


def test_duplicate_task_id_raises(tmp_path: Path) -> None:
    path = _write_temp_csv(
        tmp_path,
        [
            {"Task ID": "1", "Task name": "a"},
            {"Task ID": "1", "Task name": "b"},
        ],
    )
    with pytest.raises(AstaIntakeError, match="Duplicate Task ID"):
        parse_asta_export_csv(path)


def test_empty_csv_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(AstaIntakeError, match="empty"):
        parse_asta_export_csv(p)


def test_header_only_raises(tmp_path: Path) -> None:
    import csv

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS), lineterminator="\n")
    writer.writeheader()
    p = tmp_path / "hdr.csv"
    p.write_text(buf.getvalue(), encoding="utf-8")
    with pytest.raises(AstaIntakeError, match="No activities"):
        parse_asta_export_csv(p)


def test_deterministic_ordering_same_as_row_order(tmp_path: Path) -> None:
    path = _write_temp_csv(
        tmp_path,
        [
            {"Task ID": "z", "Task name": "last row"},
            {"Task ID": "a", "Task name": "second row"},
        ],
    )
    r1 = parse_asta_export_csv(path)
    r2 = parse_asta_export_csv(path)
    assert [a.task_id for a in r1.activities] == [a.task_id for a in r2.activities] == ["z", "a"]
    assert [a.source_row_index for a in r1.activities] == [2, 3]


def test_authoritative_shape_fixture_integration() -> None:
    """Phase 2C: committed fixture matches export column contract; parser must not crash."""
    assert FIXTURE_PATH.is_file()
    result = parse_asta_export_csv(FIXTURE_PATH)
    assert len(result.activities) == 6
    assert any("missing Task ID" in w for w in result.warnings)
    assert any("bad-date" in w for w in result.warnings)
    ids = {a.task_id for a in result.activities}
    assert ids == {"100", "101", "102", "103", "104", "105"}
    by_id = {a.task_id: a for a in result.activities}
    assert by_id["100"].source_row_index == 2


def test_utf8_bom_encoding(tmp_path: Path) -> None:
    import csv

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(ASTA_EXPORT_HEADERS), lineterminator="\n")
    writer.writeheader()
    writer.writerow({h: ("1" if h == "Task ID" else "") for h in ASTA_EXPORT_HEADERS})
    p = tmp_path / "bom.csv"
    p.write_bytes("\ufeff".encode("utf-8") + buf.getvalue().encode("utf-8"))
    result = parse_asta_export_csv(p)
    assert len(result.activities) == 1
    assert result.activities[0].task_id == "1"
    assert result.activities[0].source_row_index == 2

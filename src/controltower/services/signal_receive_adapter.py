from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from controltower.domain.models import utc_now_iso
from controltower.services.approval_ingest import ensure_approval_layout


def parse_signal_receive_text(raw_text: str) -> list[Any]:
    stripped = raw_text.strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        records: list[Any] = []
        for line_number, line in enumerate(raw_text.splitlines(), start=1):
            candidate = line.strip()
            if not candidate:
                continue
            try:
                records.append(json.loads(candidate))
            except json.JSONDecodeError as exc:  # pragma: no cover - line number branch exercised by caller
                raise ValueError(f"Signal receive payload line {line_number} is not valid JSON: {exc}") from exc
        return records

    if isinstance(parsed, list):
        return list(parsed)
    if isinstance(parsed, dict):
        for key in ("results", "messages", "envelopes", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                return list(value)
        return [parsed]
    raise ValueError("Signal receive payload must be a JSON object, array, or JSON-lines stream.")


def adapt_signal_receive_text(
    raw_text: str,
    *,
    orchestration_root: Path | None = None,
    source_path: Path | None = None,
) -> dict[str, Any]:
    return adapt_signal_receive_payloads(
        parse_signal_receive_text(raw_text),
        orchestration_root=orchestration_root,
        source_path=source_path,
    )


def adapt_signal_receive_payloads(
    payloads: list[Any],
    *,
    orchestration_root: Path | None = None,
    source_path: Path | None = None,
) -> dict[str, Any]:
    paths = ensure_approval_layout(orchestration_root)
    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, payload in enumerate(payloads, start=1):
        if not isinstance(payload, dict):
            skipped.append(
                {
                    "index": index,
                    "reason": f"Signal receive payload entry must be an object, got {type(payload).__name__}.",
                }
            )
            continue

        message = _message_text(payload)
        if not message:
            skipped.append(
                {
                    "index": index,
                    "reason": "Signal receive payload did not contain a text message.",
                }
            )
            continue

        timestamp = _message_timestamp(payload)
        message_id = _message_id(payload, index=index)
        inbox_payload = {
            "timestamp": timestamp,
            "received_at": timestamp,
            "source_channel": "signal",
            "provider": "signal_cli",
            "transport": "signal_cli",
            "message": message,
            "raw_message": message,
            "message_id": message_id,
            "source_identity": _source_identity(payload),
            "source_device": _message_value(payload, "sourceDevice", "deviceId"),
        }
        if source_path is not None:
            inbox_payload["source_payload_file"] = str(source_path.resolve())

        inbox_path = paths["inbox"] / _inbox_filename(timestamp, message_id=message_id, index=index)
        inbox_path.write_text(json.dumps(inbox_payload, indent=2), encoding="utf-8")
        written.append(
            {
                "index": index,
                "inbox_file": str(inbox_path.resolve()),
                "message_id": message_id,
                "timestamp": timestamp,
            }
        )

    return {
        "status": "ok",
        "orchestration_root": str(paths["root"]),
        "received_record_count": len(payloads),
        "written_file_count": len(written),
        "skipped_record_count": len(skipped),
        "written": written,
        "skipped": skipped,
    }


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    envelope = payload.get("envelope")
    return envelope if isinstance(envelope, dict) else payload


def _message_text(payload: dict[str, Any]) -> str | None:
    envelope = _envelope(payload)
    data_message = envelope.get("dataMessage")
    if isinstance(data_message, dict):
        for key in ("message", "body", "text"):
            value = data_message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("message", "body", "text", "raw_message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _message_timestamp(payload: dict[str, Any]) -> str:
    raw_value = _message_value(payload, "timestamp", "received_at", "sent_at", "message_timestamp")
    if raw_value is None:
        return utc_now_iso()
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if stripped:
            if stripped.isdigit():
                return _timestamp_from_epoch(int(stripped))
            return stripped
    if isinstance(raw_value, int):
        return _timestamp_from_epoch(raw_value)
    return utc_now_iso()


def _timestamp_from_epoch(value: int) -> str:
    seconds = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _message_id(payload: dict[str, Any], *, index: int) -> str:
    value = _message_value(payload, "message_id", "envelope_id", "timestamp", "id")
    if value is None:
        return f"signal-receive-{index}"
    return str(value)


def _source_identity(payload: dict[str, Any]) -> str | None:
    value = _message_value(payload, "sourceNumber", "source", "sourceUuid", "sourceName")
    if value is None:
        return None
    return _mask_phone_like(str(value))


def _message_value(payload: dict[str, Any], *keys: str) -> Any:
    envelope = _envelope(payload)
    for key in keys:
        if key in payload and payload[key] is not None and payload[key] != "":
            return payload[key]
        if key in envelope and envelope[key] is not None and envelope[key] != "":
            return envelope[key]
    return None


def _mask_phone_like(value: str) -> str:
    trimmed = value.strip()
    digits = [char for char in trimmed if char.isdigit()]
    if len(digits) < 7:
        return trimmed
    suffix = "".join(digits[-4:])
    prefix = "+" if trimmed.startswith("+") else ""
    return f"{prefix}***{suffix}"


def _inbox_filename(timestamp: str, *, message_id: str, index: int) -> str:
    safe_stamp = "".join(char if char.isalnum() else "-" for char in timestamp).strip("-") or "unknown-time"
    safe_id = "".join(char if char.isalnum() else "-" for char in message_id).strip("-") or f"entry-{index}"
    return f"signal_receive_{safe_stamp}_{safe_id}.json"

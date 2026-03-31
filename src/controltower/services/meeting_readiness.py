from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Any

from controltower.config import ControlTowerConfig, load_config
from controltower.services.controltower import ControlTowerService
from controltower.services.test_auth import build_authenticated_test_client


ARTIFACT_HEADINGS = (
    "## Scope / Timestamp",
    "## Meeting Packet",
    "## Action Queue",
    "## Continuity",
)
STALE_VAGUE_FINISH_LANGUAGE = (
    "projected finish not available",
    "no finish-date delta was emitted",
)
CATEGORY_FIRST_LABELS = (
    "Material Change",
    "High Risk",
    "Overall Posture",
)
BRIEF_SECTION_IDS = (
    "finish",
    "driver",
    "risks",
    "need",
    "doing",
)
BRIEF_SECTION_LABELS = (
    "1. Finish",
    "2. Driver",
    "3. Risks",
    "4. Need",
    "5. Doing",
)
BRIEF_BANNED_TOKENS = (
    "tracking",
    "status unavailable",
    "what changed",
    "why",
)
PACKET_ORDER_LABELS = (
    "Project:",
    "Finish:",
    "Delta:",
    "Status:",
    "Controlling driver:",
    "What changed since prior run:",
    "Challenge next:",
    "Required action(s):",
    "Supporting evidence / signals:",
    "Trust posture:",
    "Baseline posture:",
)


def verify_meeting_readiness(config: ControlTowerConfig, selected_codes: list[str] | None = None) -> dict[str, Any]:
    from controltower.api.app import create_app_from_config

    service = ControlTowerService(config)
    app = create_app_from_config(config)
    client = build_authenticated_test_client(app, config, next_path="/control")

    portfolio = service.build_portfolio()
    selected = _selected_codes(portfolio.project_rankings, selected_codes)
    tower = service.build_control_tower(selected)
    arena = service.build_arena(selected)

    root_response = client.get("/control")
    arena_response = client.get(_path("/arena", selected))
    artifact_response = client.get(_path("/arena/export/artifact.md", selected))
    detail_response = client.get(f"/projects/{selected[0]}") if selected else None

    root_html = root_response.text
    arena_html = arena_response.text
    artifact_text = artifact_response.text
    detail_html = detail_response.text if detail_response is not None else ""
    root_visibility_html = _strip_nonvisible_investigation_markup(root_html)
    arena_visibility_html = _strip_nonvisible_investigation_markup(arena_html)
    root_visible_prefix = _surface_visible_prefix(root_visibility_html, 'id="root-executive-prelude"')
    arena_visible_prefix = _surface_visible_prefix(arena_visibility_html, 'id="arena-executive-prelude"')
    root_visible_text = html.unescape(root_visible_prefix)
    arena_visible_text = html.unescape(arena_visible_prefix)
    root_focus_prefix = _prefix_until(root_visible_text, 'id="root-supporting-preview"')
    arena_focus_prefix = _prefix_until(arena_visible_text, 'id="arena-supporting-preview"')
    root_visible_word_count = _word_count(root_visible_prefix)
    arena_visible_word_count = _word_count(arena_visible_prefix)
    root_answer = tower.primary_project_answer
    arena_answers = arena.project_answers
    arena_primary = arena_answers[0] if arena_answers else None

    checks = {
        "root_execution_brief_first_screen": root_answer is not None
        and _ordered(
            root_html,
            ('id="root-executive-prelude"', 'id="root-primary-answer"', *_brief_ids("root-primary-answer"), 'id="root-supporting-preview"'),
        ),
        "root_finish_is_first": root_answer is not None and _ordered(root_visible_text, BRIEF_SECTION_LABELS),
        "root_execution_brief_visible_without_expansion": root_answer is not None and _brief_labels_visible(root_visible_text),
        "root_execution_brief_sections_complete": root_answer is not None and _brief_contract(root_answer.execution_brief),
        "root_execution_brief_is_speakable": root_answer is not None and _brief_is_speakable(root_answer.execution_brief),
        "root_top_surface_is_not_category_first": _contains_none(root_focus_prefix, CATEGORY_FIRST_LABELS),
        "root_finish_reason_is_deterministic": root_answer is not None and _answer_reason_contract(root_answer),
        "root_investigation_layer_visible_without_expansion": root_answer is not None
        and _driver_change_visible(root_visible_text, root_answer),
        "root_sections_obey_project_decision_contract": _sections_obey_project_decision_contract(
            (
                tower.material_changes_section,
                tower.required_actions_section,
                tower.rising_risks_section,
                tower.watch_items_section,
            )
        ),
        "arena_execution_brief_leads_visible_surface": arena_primary is not None
        and _ordered(
            arena_html,
            (
                'id="arena-executive-prelude"',
                'id="arena-project-answers"',
                *_brief_ids("arena-primary-answer-" + arena_primary.canonical_project_code),
                'id="arena-answer-finish-driver-' + arena_primary.canonical_project_code + '"' if arena_primary else "",
                'id="arena-answer-what-changed-' + arena_primary.canonical_project_code + '"' if arena_primary else "",
                'id="arena-supporting-preview"',
                'id="arena-executive-scan"',
            ),
        ),
        "arena_finish_is_first": arena_primary is not None and _ordered(arena_visible_text, BRIEF_SECTION_LABELS),
        "arena_execution_brief_visible_without_expansion": arena_primary is not None and _brief_labels_visible(arena_visible_text),
        "arena_execution_brief_sections_complete": arena_primary is not None
        and all(_brief_contract(answer.execution_brief) for answer in arena_answers),
        "arena_execution_brief_is_speakable": arena_primary is not None
        and all(_brief_is_speakable(answer.execution_brief) for answer in arena_answers),
        "arena_top_surface_is_not_category_first": _contains_none(arena_focus_prefix, CATEGORY_FIRST_LABELS),
        "arena_finish_reason_is_deterministic": all(_answer_reason_contract(answer) for answer in arena_answers),
        "arena_investigation_layer_visible_without_expansion": arena_primary is not None
        and _driver_change_visible(arena_visible_text, arena_primary),
        "arena_sections_obey_project_decision_contract": _sections_obey_project_decision_contract(
            (
                arena.material_changes_section,
                arena.why_it_matters_section,
                arena.required_actions_section,
                arena.rising_risks_section,
            )
        ),
        "artifact_starts_with_project_finish_answers": _ordered(artifact_text, ARTIFACT_HEADINGS),
        "artifact_preserves_finish_contract": _artifact_preserves_meeting_packet_contract(arena, artifact_text),
        "cross_surface_finish_semantics_align": _cross_surface_finish_semantics_align(root_answer, arena_primary, root_html, arena_html, artifact_text),
        "cross_surface_finish_driver_semantics_align": _cross_surface_finish_driver_semantics_align(
            root_answer,
            arena_primary,
            root_html,
            arena_html,
            detail_html,
            artifact_text,
        ),
        "packet_action_continuity_sections_present": _packet_action_continuity_sections_present(root_html, arena_html, detail_html),
        "meeting_packet_order_preserved": _meeting_packet_order_preserved(root_html, arena_html, detail_html, artifact_text),
        "action_queue_items_trackable": _action_queue_items_trackable(tower.action_queue) and _action_queue_items_trackable(arena.action_queue),
        "continuity_output_is_bounded": _continuity_output_is_bounded(tower, arena),
        "challenge_statement_is_source_backed": _challenge_statement_is_source_backed(root_answer, arena_answers, artifact_text),
        "stale_vague_finish_language_absent": _contains_none((root_html + "\n" + arena_html + "\n" + artifact_text).lower(), STALE_VAGUE_FINISH_LANGUAGE),
    }

    return {
        "status": "pass"
        if all(checks.values()) and root_response.status_code == 200 and arena_response.status_code == 200 and artifact_response.status_code == 200
        else "fail",
        "selected_codes": selected,
        "root_status_code": root_response.status_code,
        "arena_status_code": arena_response.status_code,
        "artifact_status_code": artifact_response.status_code,
        "checks": checks,
        "density": {
            "root_visible_word_count": root_visible_word_count,
            "arena_visible_word_count": arena_visible_word_count,
        },
        "root_visible_excerpt": root_visible_prefix.splitlines()[:16],
        "arena_visible_excerpt": arena_visible_prefix.splitlines()[:16],
        "artifact_excerpt": artifact_text.splitlines()[:24],
    }


def verify_meeting_readiness_from_path(config_path: Path | str) -> dict[str, Any]:
    return verify_meeting_readiness(load_config(Path(config_path)))


def _selected_codes(projects, selected_codes: list[str] | None) -> list[str]:
    if selected_codes:
        return list(selected_codes)
    return [project.canonical_project_code for project in projects[: min(2, len(projects))]]


def _ordered(text: str, tokens: tuple[str, ...]) -> bool:
    cursor = -1
    for token in tokens:
        position = text.find(token)
        if position <= cursor:
            return False
        cursor = position
    return True


def _visible_prefix(text: str) -> str:
    details_index = text.find("<details")
    return text if details_index < 0 else text[:details_index]


def _strip_nonvisible_investigation_markup(text: str) -> str:
    cleaned = re.sub(r'<div class="investigation-backdrop"[^>]*></div>', "", text, flags=re.S)
    cleaned = re.sub(r'<aside\s+class="investigation-panel"[\s\S]*?</aside>', "", cleaned, flags=re.S)
    return cleaned


def _surface_visible_prefix(text: str, anchor: str) -> str:
    start = text.find(anchor)
    if start < 0:
        return _visible_prefix(text)
    return _visible_prefix(text[start:])


def _prefix_until(text: str, token: str) -> str:
    position = text.find(token)
    return text if position < 0 else text[:position]


def _path(base: str, selected_codes: list[str]) -> str:
    if not selected_codes:
        return base
    return base + "?" + "&".join(f"selected={code}" for code in selected_codes)


def _word_count(text: str) -> int:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    tokens = [token for token in cleaned.split() if token.strip()]
    return len(tokens)


def _brief_ids(prefix: str) -> tuple[str, ...]:
    return tuple(f'id="{prefix}-{section_id}"' for section_id in BRIEF_SECTION_IDS)


def _brief_labels_visible(text: str) -> bool:
    return all(label in text for label in BRIEF_SECTION_LABELS)


def _contains_none(text: str, tokens) -> bool:
    lowered = text.lower()
    return all(str(token).lower() not in lowered for token in tokens)


def _answer_line_visible(prefix: str, label: str, reason: str | None) -> bool:
    if label in prefix:
        return True
    if reason and reason in prefix:
        return True
    return False


def _answer_reason_contract(answer) -> bool:
    if answer.projected_finish_date is None and not answer.projected_finish_reason:
        return False
    if answer.movement_days is None and not answer.movement_reason:
        return False
    if not answer.finish_driver.controlling_driver.strip():
        return False
    if not answer.finish_driver.why_it_matters.strip():
        return False
    if not answer.change_intelligence.finish.detail.strip():
        return False
    if not answer.change_intelligence.driver.detail.strip():
        return False
    if not _brief_contract(answer.execution_brief):
        return False
    return True


def _driver_change_visible(prefix: str, answer) -> bool:
    return (
        answer.finish_driver.controlling_driver in prefix
        and "Open finish driver detail" in prefix
        and "Deterministic trace" in prefix
    )


def _brief_contract(brief) -> bool:
    sections = brief.sections
    if len(sections) != len(BRIEF_SECTION_LABELS):
        return False
    if tuple(section.key for section in sections) != BRIEF_SECTION_IDS:
        return False
    if tuple(section.label for section in sections) != tuple(label.split(". ", 1)[1] for label in BRIEF_SECTION_LABELS):
        return False
    if not all(len(section.lines) == 1 for section in sections):
        return False
    if not sections[0].lines[0].startswith("Finish "):
        return False
    if not sections[1].lines[0].startswith("Driver: "):
        return False
    if not sections[2].lines[0].startswith("Risks: "):
        return False
    if not sections[3].lines[0].startswith("Need: "):
        return False
    if not sections[4].lines[0].startswith("Doing: "):
        return False
    if "confidence " not in sections[0].lines[0].lower():
        return False
    if _brief_list_item_count(sections[2].lines[0], "Risks: ") > 4:
        return False
    if any(_word_count(line) > 12 for section in sections for line in section.lines):
        return False
    if _brief_word_count(brief) > 65:
        return False
    if any(token in "\n".join(section.lines).lower() for token in BRIEF_BANNED_TOKENS for section in sections):
        return False
    if _brief_has_duplicate_lines(brief):
        return False
    return True


def _brief_is_speakable(brief) -> bool:
    for section in brief.sections:
        for line in section.lines:
            cleaned = str(line).strip()
            if not cleaned:
                return False
            if cleaned[-1] not in ".!?":
                return False
            if ";" in cleaned:
                return False
    return True


def _brief_word_count(brief) -> int:
    return sum(_word_count(line) for section in brief.sections for line in section.lines)


def _brief_has_duplicate_lines(brief) -> bool:
    seen: set[str] = set()
    for section in brief.sections:
        for line in section.lines:
            normalized = re.sub(r"[^a-z0-9]+", "", line.lower())
            if normalized in seen:
                return True
            seen.add(normalized)
    return False


def _brief_list_item_count(line: str, prefix: str) -> int:
    if not line.startswith(prefix):
        return 0
    body = line[len(prefix) :].strip().rstrip(".")
    if not body or body == "no material risk signal":
        return 0
    return len([item for item in body.split(",") if item.strip()])


def _sections_obey_project_decision_contract(sections) -> bool:
    for section in sections:
        for item in section.items:
            if not (
                item.who.strip()
                and item.finish.strip()
                and item.delta.strip()
                and item.what.strip()
                and item.why.strip()
                and item.action.strip()
                and item.cause.strip()
                and item.impact.strip()
                and item.timing.strip()
            ):
                return False
            if "projected finish" not in item.finish.lower():
                return False
            if "movement vs prior trusted run" not in item.delta.lower():
                return False
            if "unavailable" in item.finish.lower() and "reason:" not in item.finish.lower():
                return False
            if "unavailable" in item.delta.lower() and "reason:" not in item.delta.lower():
                return False
    return True


def _artifact_preserves_meeting_packet_contract(arena, artifact_text: str) -> bool:
    if not _ordered(artifact_text, PACKET_ORDER_LABELS):
        return False
    if arena.project_answers:
        for answer, packet in zip(arena.project_answers, arena.meeting_packet.items, strict=False):
            if answer.project_name not in artifact_text:
                return False
            if packet.finish_statement not in artifact_text or packet.delta_statement not in artifact_text:
                return False
            if packet.controlling_driver not in artifact_text:
                return False
            if packet.challenge_next not in artifact_text:
                return False
            if packet.trust_posture not in artifact_text or packet.baseline_posture not in artifact_text:
                return False
            if not any(action_text in artifact_text for action_text in packet.required_actions):
                return False
    return "## Meeting Packet" in artifact_text and "## Action Queue" in artifact_text and "## Continuity" in artifact_text


def _cross_surface_finish_semantics_align(root_answer, arena_primary, root_html: str, arena_html: str, artifact_text: str) -> bool:
    if root_answer is None:
        return False
    root_text = html.unescape(root_html)
    arena_text = html.unescape(arena_html)
    artifact_text = html.unescape(artifact_text)
    if root_answer.projected_finish_label not in root_text:
        return False
    if root_answer.movement_label not in root_text and not root_answer.movement_reason:
        return False
    if arena_primary is not None:
        if arena_primary.projected_finish_label not in arena_text:
            return False
        if arena_primary.required_action not in arena_text:
            return False
    return (
        f"Projected finish: {root_answer.projected_finish_label}" in artifact_text
        if root_answer.projected_finish_date
        else f"Projected finish unavailable. Reason: {root_answer.projected_finish_reason}" in artifact_text
    )


def _cross_surface_finish_driver_semantics_align(root_answer, arena_primary, root_html: str, arena_html: str, detail_html: str, artifact_text: str) -> bool:
    if root_answer is None:
        return False
    root_text = html.unescape(root_html)
    arena_text = html.unescape(arena_html)
    detail_text = html.unescape(detail_html)
    artifact_text = html.unescape(artifact_text)
    if root_answer.finish_driver.controlling_driver not in root_text:
        return False
    if root_answer.change_intelligence.finish.detail not in root_text:
        return False
    if root_answer.finish_driver.controlling_driver not in detail_text:
        return False
    if root_answer.change_intelligence.driver.detail not in detail_text:
        return False
    if arena_primary is not None:
        if arena_primary.finish_driver.controlling_driver not in arena_text:
            return False
        if arena_primary.change_intelligence.finish.detail not in arena_text:
            return False
    return (
        root_answer.finish_driver.controlling_driver in artifact_text
        and root_answer.change_intelligence.driver.detail in artifact_text
    )


def _challenge_statement_is_source_backed(root_answer, arena_answers, artifact_text: str) -> bool:
    answers = [answer for answer in [root_answer, *arena_answers] if answer is not None]
    artifact_lower = artifact_text.lower()
    for answer in answers:
        if not answer.challenge_next:
            continue
        challenge_lower = answer.challenge_next.lower()
        backed = (
            answer.finish_driver.comparison_state == "changed"
            or (answer.movement_days == 0 and answer.change_intelligence.risk.state == "changed")
            or (answer.movement_days == 0 and "cycle" in answer.finish_driver.driver_type)
            or (answer.movement_days == 0 and answer.risk_level == "HIGH")
            or (
                answer.movement_days == 0
                and "cycles remain unresolved" in challenge_lower
                and ("circular schedule logic:" in artifact_lower or "cycle(s) remain" in artifact_lower)
            )
        )
        if not backed:
            return False
        if answer.challenge_next not in artifact_text:
            return False
    return True


def _packet_action_continuity_sections_present(root_html: str, arena_html: str, detail_html: str) -> bool:
    return all(
        token in root_html
        for token in (
            'id="root-section-meeting-packet"',
            'id="root-section-action-queue"',
            'id="root-section-continuity"',
        )
    ) and all(
        token in arena_html
        for token in (
            'id="arena-section-meeting-packet"',
            'id="arena-section-action-queue"',
            'id="arena-section-continuity"',
        )
    ) and all(
        token in detail_html
        for token in (
            'id="project-detail-section-meeting-packet"',
            'id="project-detail-section-action-queue"',
            'id="project-detail-section-continuity"',
        )
    )


def _section_slice(text: str, anchor: str) -> str:
    start = text.find(anchor)
    if start < 0:
        return ""
    end = text.find("</details>", start)
    return text[start:] if end < 0 else text[start : end + len("</details>")]


def _meeting_packet_order_preserved(root_html: str, arena_html: str, detail_html: str, artifact_text: str) -> bool:
    sections = (
        _section_slice(root_html, 'id="root-section-meeting-packet"'),
        _section_slice(arena_html, 'id="arena-section-meeting-packet"'),
        _section_slice(detail_html, 'id="project-detail-section-meeting-packet"'),
        artifact_text,
    )
    return all(section and _ordered(section, PACKET_ORDER_LABELS) for section in sections)


def _action_queue_items_trackable(action_queue) -> bool:
    for group in action_queue.groups:
        for item in group.items:
            if not (
                item.queue_id.strip()
                and item.canonical_project_code.strip()
                and item.project_name.strip()
                and item.owner_role.strip()
                and item.action_text.strip()
                and item.timing.strip()
                and item.reason_source_signal.strip()
                and item.continuity_detail.strip()
            ):
                return False
            if item.priority is not None and not item.priority_basis:
                return False
    return True


def _continuity_output_is_bounded(tower, arena) -> bool:
    for continuity, action_queue in ((tower.continuity, tower.action_queue), (arena.continuity, arena.action_queue)):
        grouped_counts = {
            group.key: sum(1 for _ in group.items)
            for group in action_queue.groups
        }
        if continuity.comparison_label == "Current-run continuity only":
            if continuity.new_action_count != 0 or continuity.carry_forward_action_count != 0 or continuity.resolved_item_count != 0:
                return False
            if any(key != "comparison_unavailable" for key in grouped_counts):
                return False
        else:
            if continuity.new_action_count != grouped_counts.get("new_this_run", 0):
                return False
            if continuity.carry_forward_action_count != grouped_counts.get("carry_forward", 0):
                return False
            if continuity.resolved_item_count != len(continuity.resolved_items):
                return False
    return True

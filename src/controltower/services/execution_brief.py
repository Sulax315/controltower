from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from controltower.domain.models import ComparisonTrust, ExecutionBrief, ExecutionBriefSection, IssueDriver, ProjectSnapshot


@dataclass(frozen=True)
class CommandSignal:
    theme: str
    text: str
    score: int


class ExecutionBriefService:
    def build(self, project: ProjectSnapshot, comparison_trust: ComparisonTrust) -> ExecutionBrief:
        del comparison_trust

        confidence_label = self._confidence_label(project)
        ranked_risks = self.rank_risks(self._risk_candidates(project))
        primary_driver = self.select_primary_driver(self._driver_candidates(project, ranked_risks))
        needs = self._rank_needs(self._need_candidates(project, ranked_risks))
        doing = self._doing_candidates(needs, project)
        return self._reduce_sections(project, confidence_label, primary_driver, ranked_risks, needs, doing)

    def select_primary_driver(self, drivers: list[CommandSignal]) -> CommandSignal | None:
        if not drivers:
            return None
        return sorted(drivers, key=lambda item: (-item.score, item.text))[0]

    def rank_risks(self, risks: list[CommandSignal]) -> list[CommandSignal]:
        strongest: dict[str, CommandSignal] = {}
        for risk in risks:
            existing = strongest.get(risk.theme)
            if existing is None or risk.score > existing.score:
                strongest[risk.theme] = risk
        return sorted(strongest.values(), key=lambda item: (-item.score, item.text))[:4]

    def _reduce_sections(
        self,
        project: ProjectSnapshot,
        confidence_label: str,
        primary_driver: CommandSignal | None,
        ranked_risks: list[CommandSignal],
        needs: list[str],
        doing: list[str],
    ) -> ExecutionBrief:
        return ExecutionBrief(
            finish_summary=ExecutionBriefSection(
                key="finish",
                label="Finish",
                lines=[self._finish_line(project, confidence_label)],
            ),
            driver_statement=ExecutionBriefSection(
                key="driver",
                label="Driver",
                lines=[self._driver_line(primary_driver)],
            ),
            risks_list=ExecutionBriefSection(
                key="risks",
                label="Risks",
                lines=[self._risk_line(ranked_risks)],
            ),
            need_statement=ExecutionBriefSection(
                key="need",
                label="Need",
                lines=[self._need_line(needs)],
            ),
            doing_statement=ExecutionBriefSection(
                key="doing",
                label="Doing",
                lines=[self._doing_line(doing)],
            ),
        )

    def _finish_line(self, project: ProjectSnapshot, confidence_label: str) -> str:
        fragments = [
            f"Finish {self._format_date(project.delta.schedule.current_finish_date or (project.schedule.finish_date if project.schedule else None))}",
            self._finish_delta_fragment(project),
            f"Confidence {confidence_label}",
        ]
        return self._punctuate(". ".join(fragment for fragment in fragments if fragment))

    def _driver_line(self, primary_driver: CommandSignal | None) -> str:
        if primary_driver is None:
            return "Driver: unavailable."
        return self._punctuate(f"Driver: {primary_driver.text}")

    def _risk_line(self, ranked_risks: list[CommandSignal]) -> str:
        if not ranked_risks:
            return "Risks: no material risk signal."
        return self._punctuate(f"Risks: {', '.join(risk.text for risk in ranked_risks)}")

    def _need_line(self, needs: list[str]) -> str:
        if not needs:
            return "Need: confirm next action."
        return self._punctuate(f"Need: {', '.join(needs[:3])}")

    def _doing_line(self, doing: list[str]) -> str:
        if not doing:
            return "Doing: confirming next action."
        return self._punctuate(f"Doing: {', '.join(doing[:3])}")

    def _driver_candidates(self, project: ProjectSnapshot, ranked_risks: list[CommandSignal]) -> list[CommandSignal]:
        candidates: list[CommandSignal] = []
        if project.finish_driver.controlling_driver and project.finish_driver.controlling_driver != "Driver unavailable":
            label = self._short_driver_label(project.finish_driver.controlling_driver)
            reason = self._driver_reason(project.finish_driver.why_it_matters)
            text = f"{label} - {reason}" if reason else label
            candidates.append(CommandSignal(theme="finish driver", text=text, score=200))
        elif project.schedule and project.schedule.top_drivers:
            driver = project.schedule.top_drivers[0]
            label = self._short_driver_label(driver.label)
            reason = self._driver_reason(driver.rationale)
            text = f"{label} - {reason}" if reason else label
            candidates.append(CommandSignal(theme="schedule driver", text=text, score=180))

        if not candidates and project.schedule and (project.schedule.risk_path_count or 0) > 0:
            candidates.append(
                CommandSignal(
                    theme="risk path",
                    text=f"risk path ({project.schedule.risk_path_count})",
                    score=60,
                )
            )
        if not candidates and ranked_risks:
            candidates.append(CommandSignal(theme=ranked_risks[0].theme, text=ranked_risks[0].text, score=40))
        return candidates

    def _risk_candidates(self, project: ProjectSnapshot) -> list[CommandSignal]:
        candidates: list[CommandSignal] = []
        schedule = project.schedule
        if schedule:
            open_ends = (schedule.open_start_count or 0) + (schedule.open_finish_count or 0)
            if (schedule.negative_float_count or 0) > 0:
                candidates.append(
                    CommandSignal(
                        theme="negative float",
                        text=f"negative float ({schedule.negative_float_count})",
                        score=120 + min(schedule.negative_float_count, 9),
                    )
                )
            if open_ends > 0:
                candidates.append(
                    CommandSignal(
                        theme="open ends",
                        text=f"open ends ({open_ends})",
                        score=110 + min(open_ends, 9),
                    )
                )
            if (schedule.cycle_count or 0) > 0:
                candidates.append(
                    CommandSignal(
                        theme="cycle",
                        text=f"cycle ({schedule.cycle_count})",
                        score=100 + min(schedule.cycle_count, 9),
                    )
                )
            if (schedule.negative_float_count or 0) == 0 and project.delta.schedule.float_movement_days is not None and project.delta.schedule.float_movement_days < 0:
                candidates.append(
                    CommandSignal(
                        theme="float",
                        text=f"float compression ({self._format_day_delta(project.delta.schedule.float_movement_days)})",
                        score=95,
                    )
                )

        material_financial = self._material_financial_themes(project)
        for issue in project.top_issues:
            signal = self._risk_signal_from_issue(issue, project, material_financial)
            if signal is not None:
                candidates.append(signal)
        for token in project.delta.risk.new_risks:
            signal = self._risk_signal_from_token(token, material_financial)
            if signal is not None:
                candidates.append(signal)
        return candidates

    def _risk_signal_from_issue(
        self,
        issue: IssueDriver,
        project: ProjectSnapshot,
        material_financial: set[str],
    ) -> CommandSignal | None:
        lowered = issue.label.lower()
        schedule = project.schedule
        open_ends = ((schedule.open_start_count or 0) + (schedule.open_finish_count or 0)) if schedule else 0
        if "cycle" in lowered or "circular" in lowered:
            text = f"cycle ({schedule.cycle_count})" if schedule and (schedule.cycle_count or 0) > 0 else "cycle"
            return CommandSignal(theme="cycle", text=text, score=100)
        if "negative float" in lowered:
            text = (
                f"negative float ({schedule.negative_float_count})"
                if schedule and (schedule.negative_float_count or 0) > 0
                else "negative float"
            )
            return CommandSignal(theme="negative float", text=text, score=120)
        if "open-end" in lowered or "open end" in lowered:
            text = f"open ends ({open_ends})" if open_ends > 0 else "open ends"
            return CommandSignal(theme="open ends", text=text, score=110)
        if "profit fade" in lowered and "profit" in material_financial:
            return CommandSignal(theme="profit", text="profit fade", score=82)
        if "margin" in lowered and "margin" in material_financial:
            return CommandSignal(theme="margin", text="margin erosion", score=80)
        if ("cost" in lowered or "variance" in lowered) and "cost" in material_financial:
            return CommandSignal(theme="cost", text="cost drift", score=84)
        if "new risks surfaced" in lowered:
            return None
        return None

    def _risk_signal_from_token(self, value: str | None, material_financial: set[str]) -> CommandSignal | None:
        token = str(value or "").strip().lower()
        if not token:
            return None
        mapped = {
            "commitment_spike": CommandSignal(theme="commitment spike", text="commitment spike", score=76),
            "forecast_growth_risk": CommandSignal(theme="forecast growth risk", text="forecast growth risk", score=74),
            "negative_float": CommandSignal(theme="negative float", text="negative float", score=120),
            "open_ends": CommandSignal(theme="open ends", text="open ends", score=110),
            "schedule_open_ends": CommandSignal(theme="open ends", text="open ends", score=110),
            "schedule_cycles": CommandSignal(theme="cycle", text="cycle", score=100),
        }
        if token in mapped:
            return mapped[token]
        if token == "margin_compression" and "margin" in material_financial:
            return CommandSignal(theme="margin", text="margin erosion", score=80)
        if token == "profit_fade" and "profit" in material_financial:
            return CommandSignal(theme="profit", text="profit fade", score=82)
        if token in {"cost_variance_growth", "cost_overrun"} and "cost" in material_financial:
            return CommandSignal(theme="cost", text="cost drift", score=84)
        label = self._humanize_token(token)
        if not label or label in {"margin compression", "profit fade"}:
            return None
        return CommandSignal(theme=label, text=label, score=60)

    def _material_financial_themes(self, project: ProjectSnapshot) -> set[str]:
        themes: set[str] = set()
        if project.delta.financial.cost_variance_change is not None and abs(project.delta.financial.cost_variance_change) >= 50000:
            themes.add("cost")
        if project.delta.financial.margin_movement is not None and project.delta.financial.margin_movement <= -1.0:
            themes.add("margin")
        for issue in project.top_issues:
            if issue.source != "financial" or issue.severity != "high":
                continue
            lowered = issue.label.lower()
            if "profit" in lowered:
                themes.add("profit")
            if "margin" in lowered:
                themes.add("margin")
            if "cost" in lowered or "variance" in lowered:
                themes.add("cost")
        return themes

    def _need_candidates(self, project: ProjectSnapshot, ranked_risks: list[CommandSignal]) -> list[str]:
        needs: list[str] = []
        for action in project.health.required_actions[:4]:
            phrase = self._need_from_action(action.action, ranked_risks)
            if phrase:
                needs.append(phrase)
        if not needs:
            needs.extend(self._risk_need_phrase(risk.theme) for risk in ranked_risks[:3])
        return needs

    def _rank_needs(self, needs: list[str]) -> list[str]:
        unique = self._unique_phrases(needs)
        return sorted(unique, key=lambda item: (-self._need_priority(item), item))[:3]

    def _need_from_action(self, action_text: str, ranked_risks: list[CommandSignal]) -> str:
        lowered = self._normalize_action_phrase(action_text)
        if "remove" in lowered and "cycle" in lowered:
            return "remove cycle"
        if "close" in lowered and "open ends" in lowered:
            return "close open ends"
        if "lock" in lowered and "steel release" in lowered:
            return "release steel package"
        if "mitigate" in lowered and "risk" in lowered:
            specific = self._specific_non_schedule_need(ranked_risks)
            if specific:
                return specific
            return "recover float"
        return self._clean_fragment(lowered, max_words=4).lower()

    def _specific_non_schedule_need(self, ranked_risks: list[CommandSignal]) -> str:
        for risk in ranked_risks:
            if risk.theme in {"negative float", "open ends", "cycle", "float"}:
                continue
            return self._risk_need_phrase(risk.theme)
        return ""

    def _risk_need_phrase(self, theme: str) -> str:
        mapping = {
            "negative float": "recover float",
            "float": "recover float",
            "open ends": "close open ends",
            "cycle": "remove cycle",
            "cost": "address cost drift",
            "margin": "recover margin",
            "profit": "review profit exposure",
            "commitment spike": "review commitment spike",
            "forecast growth risk": "review forecast growth risk",
        }
        return mapping.get(theme, f"review {theme}")

    def _doing_candidates(self, needs: list[str], project: ProjectSnapshot) -> list[str]:
        doing = [self._doing_from_need(need) for need in needs]
        if doing:
            return self._unique_phrases(doing)[:3]
        for item in project.action_queue[:3]:
            action = self._need_from_action(item.action_text, [])
            if action:
                doing.append(self._doing_from_need(action))
        return self._unique_phrases(doing)[:3]

    def _doing_from_need(self, need: str) -> str:
        lowered = need.lower()
        if "remove cycle" in lowered:
            return "resolving cycle"
        if "close open ends" in lowered:
            return "closing open ends"
        if "recover float" in lowered:
            return "recovering float"
        if "address cost drift" in lowered:
            return "reviewing cost exposure"
        if "recover margin" in lowered:
            return "reviewing margin recovery"
        if "review profit exposure" in lowered:
            return "reviewing profit exposure"
        if "review commitment spike" in lowered:
            return "reviewing commitment spike"
        if "review forecast growth risk" in lowered:
            return "reviewing forecast growth risk"
        if "release steel package" in lowered:
            return "finalizing steel release"
        words = lowered.split()
        if not words:
            return "confirming next action"
        if words[0].endswith("e") and words[0] not in {"close", "remove"}:
            words[0] = words[0][:-1] + "ing"
        elif words[0] == "close":
            words[0] = "closing"
        elif words[0] == "remove":
            words[0] = "removing"
        else:
            words[0] = words[0] + "ing"
        return " ".join(words[:4])

    def _need_priority(self, value: str) -> int:
        lowered = value.lower()
        if "remove cycle" in lowered:
            return 120
        if "close open ends" in lowered:
            return 110
        if "recover float" in lowered:
            return 100
        if "release steel package" in lowered:
            return 95
        if "cost drift" in lowered:
            return 90
        if "margin" in lowered or "profit" in lowered:
            return 85
        return 80

    def _finish_delta_fragment(self, project: ProjectSnapshot) -> str:
        if project.comparison_status != "trusted":
            return "No baseline"
        movement = project.delta.schedule.finish_date_movement_days
        if movement is None:
            return "Delta unavailable"
        if movement == 0:
            return "Delta 0d"
        return f"Delta {self._format_day_delta(movement)}"

    def _driver_reason(self, value: str | None) -> str:
        if not value or "no published finish-driver signal" in value.lower():
            return ""
        return self._clean_fragment(re.split(r"[.;]", value, maxsplit=1)[0], max_words=4)

    def _normalize_action_phrase(self, action_text: str) -> str:
        cleaned = " ".join(str(action_text or "").split()).strip().lower().rstrip(".")
        replacements = (
            ("validate and remove ", "remove "),
            ("validate missing successors and predecessors across ", "close "),
            ("schedule cycle(s)", "cycle"),
            ("cycle(s)", "cycle"),
            ("open-end activities", "open ends"),
            ("open end activities", "open ends"),
            ("the newly surfaced risk signals", "risks"),
            ("risk signals", "risks"),
            ("the steel release package", "steel release package"),
        )
        for source, target in replacements:
            cleaned = cleaned.replace(source, target)
        cleaned = re.sub(r"\bbefore the next [^.]+", "", cleaned)
        cleaned = re.sub(r"\bbefore next [^.]+", "", cleaned)
        cleaned = re.sub(r"\bthis week\b", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:-")
        return cleaned

    def _confidence_label(self, project: ProjectSnapshot) -> str:
        if not (project.delta.schedule.current_finish_date or (project.schedule.finish_date if project.schedule else None)):
            return "low"
        if project.trust_indicator.status in {"low", "missing"}:
            return "low"
        if project.comparison_status == "trusted" and project.trust_indicator.status == "high":
            return "high"
        return "medium"

    def _short_driver_label(self, label: str) -> str:
        cleaned = " ".join(str(label or "").split()).strip()
        if " - " in cleaned:
            cleaned = cleaned.split(" - ", 1)[1]
        return self._clean_fragment(cleaned, max_words=3)

    def _format_day_delta(self, value: int | float) -> str:
        sign = "+" if value > 0 else "-"
        magnitude = abs(value)
        if float(magnitude).is_integer():
            return f"{sign}{int(magnitude)}d"
        return f"{sign}{magnitude:.1f}d"

    def _humanize_token(self, value: str | None) -> str:
        cleaned = " ".join(str(value or "").replace("_", " ").split()).strip(" .,;:-")
        return cleaned.lower()

    def _unique_phrases(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = self._clean_fragment(value, max_words=4).lower()
            if not cleaned:
                continue
            key = re.sub(r"[^a-z0-9]+", "", cleaned)
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
        return result

    def _clean_fragment(self, text: str | None, *, max_words: int) -> str:
        cleaned = " ".join(str(text or "").split()).strip(" .,;:-")
        if not cleaned:
            return ""
        words = cleaned.split()
        if len(words) > max_words:
            cleaned = " ".join(words[:max_words])
        return cleaned

    def _punctuate(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return ""
        if cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned

    def _format_date(self, value: str | None) -> str:
        if not value:
            return "unavailable"
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")
        except ValueError:
            return value

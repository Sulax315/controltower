"""Minimal CLI validation for Asta CSV intake and schedule logic graph (Phase 2C / 3A harness)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .asta_csv import parse_asta_export_csv
from .command_brief import build_command_brief
from .delta_analysis import ScheduleDeltaResult, compare_schedule_csv_paths
from .drivers import rank_driver_candidates
from .export_artifacts import compute_sha256_bytes, export_deterministic_artifact_set
from .normalized_intake import build_normalized_intake_payload
from .exploration import (
    all_simple_paths_between,
    downstream_closure,
    downstream_impact_span,
    explain_driver_structure,
    immediate_predecessors,
    immediate_successors,
    is_reachable,
    shared_ancestors,
    shared_descendants,
    shortest_path_between,
    upstream_closure,
)
from .output_contracts import build_exploration_contract, build_schedule_intelligence_bundle
from .risks import collect_schedule_risk_findings
from .graph import ScheduleLogicGraph, build_logic_graph_payload, build_schedule_logic_graph
from .graph_summary import (
    build_schedule_graph_summary,
    reachable_downstream_nodes,
    reachable_upstream_nodes,
    top_nodes_by_in_degree,
    top_nodes_by_out_degree,
)
from .logic_quality import LogicQualitySignals, analyze_logic_quality
from .models import Activity


def _format_activity_clean(a: Activity, *, index: int) -> str:
    """Readable multi-line summary for validation logs (Phase 2C evidence)."""
    lines = [
        f"--- activity[{index}] ---",
        f"  source_row_index={a.source_row_index!r}",
        f"  task_id={a.task_id!r}  unique_task_id={a.unique_task_id!r}",
        f"  task_name={a.task_name!r}",
        f"  start={a.start!r}  finish={a.finish!r}  duration_days={a.duration_days!r}  duration_remaining_days={a.duration_remaining_days!r}",
        f"  early_start={a.early_start!r}  early_finish={a.early_finish!r}  late_start={a.late_start!r}  late_finish={a.late_finish!r}",
        f"  total_float_days={a.total_float_days!r}  free_float_days={a.free_float_days!r}  critical_path_drag_days={a.critical_path_drag_days!r}",
        f"  critical={a.critical!r}  percent_complete={a.percent_complete!r}",
        f"  predecessors={a.predecessors!r}  successors={a.successors!r}",
        f"  original_start={a.original_start!r}  original_finish={a.original_finish!r}",
        f"  phase_exec={a.phase_exec!r}  control_account={a.control_account!r}  area_zone={a.area_zone!r}",
    ]
    return "\n".join(lines)


def _edge_count(graph: ScheduleLogicGraph) -> int:
    return sum(len(es) for es in graph.outbound_edges_by_id.values())


def _print_graph_section(graph: ScheduleLogicGraph) -> None:
    n = len(graph.nodes_by_id)
    m = _edge_count(graph)
    print()
    print("=== Schedule logic graph (Phase 3A) ===")
    print(f"Node count: {n}")
    print(f"Edge count (unique directed): {m}")
    print(f"Invalid reference count: {len(graph.invalid_references)}")
    print(f"No-predecessor node count: {len(graph.no_predecessor_nodes)}")
    print(f"No-successor node count: {len(graph.no_successor_nodes)}")
    if graph.invalid_references:
        print("Sample invalid references (up to 5):")
        for ir in graph.invalid_references[:5]:
            print(f"  {ir.referencing_task_id} {ir.role} -> missing {ir.referenced_task_id!r}")
    print("Sample nodes (up to 3):")
    for tid in sorted(graph.nodes_by_id)[:3]:
        inn = graph.inbound_edges_by_id.get(tid, [])
        out = graph.outbound_edges_by_id.get(tid, [])
        name = graph.nodes_by_id[tid].task_name
        print(f"  {tid!r} name={name!r} inbound={inn} outbound={out}")
    print("Sample edges (up to 6):")
    shown = 0
    for tid in sorted(graph.nodes_by_id):
        for e in graph.outbound_edges_by_id.get(tid, []):
            print(f"  {e[0]!r} -> {e[1]!r}")
            shown += 1
            if shown >= 6:
                return
    return


def _print_logic_quality_section(signals: LogicQualitySignals) -> None:
    print()
    print("=== Logic quality (Phase 3B) ===")
    print(f"Open-end source count (no inbound edges): {len(signals.open_end_sources)}")
    print(f"Open-end sink count (no outbound edges): {len(signals.open_end_sinks)}")
    if signals.open_end_sources:
        print(f"  sample sources: {list(signals.open_end_sources[:5])}")
    if signals.open_end_sinks:
        print(f"  sample sinks: {list(signals.open_end_sinks[:5])}")
    print(f"Invalid reference count: {len(signals.invalid_references)}")
    if signals.invalid_references:
        for ir in signals.invalid_references[:3]:
            print(f"  {ir.referencing_task_id} {ir.role} -> missing {ir.referenced_task_id!r}")
    print(f"Asymmetric relationship count: {len(signals.asymmetric_relationships)}")
    for ar in signals.asymmetric_relationships[:5]:
        parts = []
        if ar.missing_on_predecessor_side:
            parts.append("to_task lacks predecessor link")
        if ar.missing_on_successor_side:
            parts.append("from_task lacks successor link")
        print(f"  {ar.from_task_id!r} -> {ar.to_task_id!r}: {', '.join(parts)}")
    if signals.cycle_witness:
        print(f"Cycle witness (one): {list(signals.cycle_witness)}")
    else:
        print("Cycle witness: none (acyclic on this check)")


def _print_graph_summary_section(graph: ScheduleLogicGraph) -> None:
    s = build_schedule_graph_summary(graph)
    ds = s.degree_stats
    print()
    print("=== Graph summary (Phase 3C) ===")
    print(f"node_count: {s.node_count}")
    print(f"edge_count: {s.edge_count}")
    print(f"invalid_reference_count: {s.invalid_reference_count}")
    print(f"open_source_count (zero inbound): {s.open_source_node_count}")
    print(f"open_sink_count (zero outbound): {s.open_sink_node_count}")
    print(f"directed_cycle_present: {s.directed_cycle_present}")
    print(f"directed_cycle_witness_length: {s.directed_cycle_witness_length}")
    print("in-degree: min / max / mean")
    print(f"  {ds.min_in_degree} / {ds.max_in_degree} / {ds.mean_in_degree:.6f}")
    print("out-degree: min / max / mean")
    print(f"  {ds.min_out_degree} / {ds.max_out_degree} / {ds.mean_out_degree:.6f}")
    print(f"zero_inbound_node_count: {ds.zero_inbound_node_count}")
    print(f"zero_outbound_node_count: {ds.zero_outbound_node_count}")
    print(f"top by out-degree: {list(top_nodes_by_out_degree(graph, limit=5))}")
    print(f"top by in-degree: {list(top_nodes_by_in_degree(graph, limit=5))}")
    sample_tid = "101" if "101" in graph.nodes_by_id else next(iter(sorted(graph.nodes_by_id)), None)
    if sample_tid is not None:
        up = sorted(reachable_upstream_nodes(graph, sample_tid, max_depth=2))
        down = sorted(reachable_downstream_nodes(graph, sample_tid, max_depth=2))
        print(f"sample reachability (task_id={sample_tid!r}, max_depth=2):")
        print(f"  upstream_nodes: {up}")
        print(f"  downstream_nodes: {down}")


def _print_delta_section(result: ScheduleDeltaResult) -> None:
    sc = result.summary_counts
    print()
    print("=== Schedule delta (Phase 4C) ===")
    print(f"baseline_task_count: {result.baseline_task_count}")
    print(f"current_task_count: {result.current_task_count}")
    print(f"added_task_count: {sc.added_tasks}")
    print(f"removed_task_count: {sc.removed_tasks}")
    print(f"finish_date_change_count: {sc.changed_finish_dates}")
    print(f"start_date_change_count: {sc.changed_start_dates}")
    print(f"logic_edge_added_count: {sc.logic_edges_added}")
    print(f"logic_edge_removed_count: {sc.logic_edges_removed}")
    print(f"predecessor_set_change_count: {sc.predecessor_set_changes}")
    print(f"successor_set_change_count: {sc.successor_set_changes}")
    print(f"driver_rank_change_count: {sc.driver_rank_changes}")
    print(f"sample_added_task_ids: {list(result.added_task_ids[:5])}")
    print(f"sample_removed_task_ids: {list(result.removed_task_ids[:5])}")
    print(f"sample_finish_changes: {[f'{x.task_id}:{x.old_value}->{x.new_value}' for x in result.changed_finish_dates[:4]]}")
    print(f"sample_edges_added: {list(result.logic_edges_added[:6])}")
    print(f"sample_edges_removed: {list(result.logic_edges_removed[:6])}")


def _print_risks_section(graph: ScheduleLogicGraph, *, top: int) -> None:
    findings = collect_schedule_risk_findings(graph)
    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f.risk_type] = by_type.get(f.risk_type, 0) + 1
    print()
    print(f"=== Risk findings (Phase 4B, top {top} of {len(findings)}) ===")
    print(f"total_risk_count: {len(findings)}")
    print(f"counts_by_type: {dict(sorted(by_type.items()))}")
    for i, r in enumerate(findings[:top], start=1):
        print(f"{i}. [{r.severity}] {r.risk_id} type={r.risk_type} score={r.sort_score}")
        print(f"   task_id={r.task_id!r} related={list(r.related_task_ids)}")
        print(f"   evidence={dict(r.evidence)}")
        print(f"   sources={list(r.source_signals)}")


def _print_drivers_section(graph: ScheduleLogicGraph, *, top: int) -> None:
    ranked = rank_driver_candidates(graph, limit=top)
    print()
    print(f"=== Driver candidates (Phase 4A, top {top}) ===")
    for i, c in enumerate(ranked, start=1):
        print(f"{i}. task_id={c.task_id!r} score={c.driver_score} name={c.task_name!r}")
        print(f"   components: {c.score_components}")
        print(f"   signals: {c.rationale_signals}")


def _print_exploration_queries(
    graph: ScheduleLogicGraph,
    *,
    upstream_task_id: str | None,
    downstream_task_id: str | None,
    path_pair: tuple[str, str] | None,
    all_paths_pair: tuple[str, str] | None,
    shared_ancestors_pair: tuple[str, str] | None,
    shared_descendants_pair: tuple[str, str] | None,
    driver_structure_task_id: str | None,
    impact_span_task_id: str | None,
) -> None:
    if upstream_task_id is not None:
        print(f"upstream:{upstream_task_id}={list(upstream_closure(graph, upstream_task_id))}")
        print(f"immediate_predecessors:{upstream_task_id}={list(immediate_predecessors(graph, upstream_task_id))}")
    if downstream_task_id is not None:
        print(f"downstream:{downstream_task_id}={list(downstream_closure(graph, downstream_task_id))}")
        print(f"immediate_successors:{downstream_task_id}={list(immediate_successors(graph, downstream_task_id))}")
    if path_pair is not None:
        src, dst = path_pair
        print(f"path:{src}->{dst}={list(shortest_path_between(graph, src, dst))}")
        print(f"reachable:{src}->{dst}={is_reachable(graph, src, dst)}")
    if all_paths_pair is not None:
        src, dst = all_paths_pair
        all_paths = all_simple_paths_between(graph, src, dst)
        print(f"all_paths:{src}->{dst}={len(all_paths)}")
        for p in all_paths:
            print(f"path={list(p)}")
    if shared_ancestors_pair is not None:
        left, right = shared_ancestors_pair
        print(f"shared_ancestors:{left},{right}={list(shared_ancestors(graph, left, right))}")
    if shared_descendants_pair is not None:
        left, right = shared_descendants_pair
        print(f"shared_descendants:{left},{right}={list(shared_descendants(graph, left, right))}")
    if driver_structure_task_id is not None:
        ds = explain_driver_structure(graph, driver_structure_task_id)
        print(f"driver_structure:{driver_structure_task_id}={ds}")
    if impact_span_task_id is not None:
        span = downstream_impact_span(graph, impact_span_task_id)
        print(f"impact_span:{impact_span_task_id}={span}")


def run_summary(
    csv_path: Path,
    *,
    include_graph: bool,
    logic_quality: bool,
    graph_summary: bool,
    drivers_top: int | None,
    risks_top: int | None,
    brief: bool,
    upstream_task_id: str | None,
    downstream_task_id: str | None,
    path_pair: tuple[str, str] | None,
    all_paths_pair: tuple[str, str] | None,
    shared_ancestors_pair: tuple[str, str] | None,
    shared_descendants_pair: tuple[str, str] | None,
    driver_structure_task_id: str | None,
    impact_span_task_id: str | None,
    export_dir: Path | None,
) -> int:
    result = parse_asta_export_csv(csv_path)
    acts = result.activities

    def _has_pred(a: Activity) -> bool:
        return bool(a.predecessors)

    def _has_succ(a: Activity) -> bool:
        return bool(a.successors)

    def _is_critical(a: Activity) -> bool:
        return a.critical is True

    print(f"Parsed activities: {len(acts)}")
    for w in result.warnings:
        print(f"WARNING: {w}")

    for i, a in enumerate(acts[:3]):
        print(_format_activity_clean(a, index=i))
        print(json.dumps(a.model_dump(mode="json"), indent=2, default=str))

    print(f"With predecessors: {sum(1 for a in acts if _has_pred(a))}")
    print(f"With successors: {sum(1 for a in acts if _has_succ(a))}")
    print(f"Critical (True): {sum(1 for a in acts if _is_critical(a))}")

    if include_graph:
        graph = build_schedule_logic_graph(acts)
        _print_graph_section(graph)
        if logic_quality:
            _print_logic_quality_section(analyze_logic_quality(graph))
        if graph_summary:
            _print_graph_summary_section(graph)
        if drivers_top is not None:
            _print_drivers_section(graph, top=drivers_top)
        if risks_top is not None:
            _print_risks_section(graph, top=risks_top)
        if brief:
            gs = build_schedule_graph_summary(graph)
            ranked = rank_driver_candidates(graph, limit=1)
            drv = ranked[0] if ranked else None
            risks = collect_schedule_risk_findings(graph, graph_summary=gs)
            cb = build_command_brief(graph_summary=gs, driver=drv, risks=risks, delta=None)
            for ln in cb.as_lines():
                print(ln)
        _print_exploration_queries(
            graph,
            upstream_task_id=upstream_task_id,
            downstream_task_id=downstream_task_id,
            path_pair=path_pair,
            all_paths_pair=all_paths_pair,
            shared_ancestors_pair=shared_ancestors_pair,
            shared_descendants_pair=shared_descendants_pair,
            driver_structure_task_id=driver_structure_task_id,
            impact_span_task_id=impact_span_task_id,
        )
        if export_dir is not None:
            gs = build_schedule_graph_summary(graph)
            lq = analyze_logic_quality(graph)
            ranked = rank_driver_candidates(graph, limit=1)
            top = ranked[0] if ranked else None
            risks = collect_schedule_risk_findings(graph, logic_quality=lq, graph_summary=gs)
            brief_obj = build_command_brief(graph_summary=gs, driver=top, risks=risks, delta=None)
            ex = build_exploration_contract(
                immediate_predecessors=immediate_predecessors(graph, upstream_task_id)
                if upstream_task_id is not None
                else (),
                immediate_successors=immediate_successors(graph, downstream_task_id)
                if downstream_task_id is not None
                else (),
                upstream_closure=upstream_closure(graph, upstream_task_id) if upstream_task_id is not None else (),
                downstream_closure=downstream_closure(graph, downstream_task_id) if downstream_task_id is not None else (),
                shortest_path=shortest_path_between(graph, path_pair[0], path_pair[1]) if path_pair is not None else (),
                all_simple_paths=all_simple_paths_between(graph, all_paths_pair[0], all_paths_pair[1])
                if all_paths_pair is not None
                else (),
                shared_ancestors=shared_ancestors(graph, shared_ancestors_pair[0], shared_ancestors_pair[1])
                if shared_ancestors_pair is not None
                else (),
                shared_descendants=shared_descendants(graph, shared_descendants_pair[0], shared_descendants_pair[1])
                if shared_descendants_pair is not None
                else (),
                driver_structure=explain_driver_structure(graph, driver_structure_task_id)
                if driver_structure_task_id is not None
                else None,
                impact_span=downstream_impact_span(graph, impact_span_task_id) if impact_span_task_id is not None else None,
            )
            bundle = build_schedule_intelligence_bundle(
                graph_summary=gs,
                logic_quality=lq,
                top_driver=top,
                risks=risks,
                delta=None,
                command_brief=brief_obj,
                exploration=ex,
            )
            src_bytes = csv_path.read_bytes()
            normalized_intake = build_normalized_intake_payload(
                acts,
                warnings=tuple(result.warnings),
                source_display_name=csv_path.name,
                source_sha256_hex=compute_sha256_bytes(src_bytes),
            )
            logic_graph = build_logic_graph_payload(graph)
            artifacts, manifest = export_deterministic_artifact_set(
                export_dir,
                bundle=bundle,
                normalized_intake=normalized_intake,
                logic_graph=logic_graph,
            )
            print(f"export_dir={export_dir}")
            for a in artifacts:
                print(f"artifact:{a.filename} sha256={a.sha256} bytes={a.byte_count} type={a.artifact_type}")
            print(
                "manifest_flags:"
                f" bundle={manifest.bundle_present}"
                f" brief={manifest.command_brief_present}"
                f" snapshot={manifest.engine_snapshot_present}"
                f" exploration={manifest.exploration_present}"
                f" normalized_intake={manifest.normalized_intake_present}"
                f" logic_graph={manifest.logic_graph_present}"
            )

    return 0


def run_delta(baseline_csv: Path, current_csv: Path) -> int:
    if not baseline_csv.is_file():
        print(f"Baseline file not found: {baseline_csv}", file=sys.stderr)
        return 1
    if not current_csv.is_file():
        print(f"Current file not found: {current_csv}", file=sys.stderr)
        return 1
    result = compare_schedule_csv_paths(baseline_csv, current_csv)
    _print_delta_section(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate Asta CSV export parsing and optional logic graph.")
    p.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        type=Path,
        help="Path to the Asta export .csv file (omit when using --delta).",
    )
    p.add_argument(
        "--no-graph",
        action="store_true",
        help="Skip schedule logic graph construction (parse-only).",
    )
    p.add_argument(
        "--logic-quality",
        action="store_true",
        help="After graph build, print open ends, invalid refs, asymmetry, and cycle witness (Phase 3B).",
    )
    p.add_argument(
        "--graph-summary",
        action="store_true",
        help="After graph build, print structural metrics and bounded reachability sample (Phase 3C).",
    )
    p.add_argument(
        "--drivers",
        type=int,
        nargs="?",
        const=8,
        default=None,
        metavar="N",
        help="After graph build, print top N driver candidates (default: 8). Phase 4A.",
    )
    p.add_argument(
        "--risks",
        type=int,
        nargs="?",
        const=12,
        default=None,
        metavar="N",
        help="After graph build, print risk summary and top N findings (default: 12). Phase 4B.",
    )
    p.add_argument(
        "--delta",
        nargs=2,
        type=Path,
        metavar=("BASELINE_CSV", "CURRENT_CSV"),
        help="Compare two Asta exports (baseline then current). Mutually exclusive with single-file mode.",
    )
    p.add_argument(
        "--brief",
        action="store_true",
        help="After graph build, print the five-line deterministic command brief (Phase 5A).",
    )
    p.add_argument("--upstream", metavar="TASK_ID", help="Print upstream closure for TASK_ID.")
    p.add_argument("--downstream", metavar="TASK_ID", help="Print downstream closure for TASK_ID.")
    p.add_argument("--path", nargs=2, metavar=("SOURCE", "TARGET"), help="Print shortest path and reachability.")
    p.add_argument(
        "--all-paths",
        nargs=2,
        metavar=("SOURCE", "TARGET"),
        help="Print bounded all-simple-paths between SOURCE and TARGET.",
    )
    p.add_argument("--shared-ancestors", nargs=2, metavar=("A", "B"), help="Print shared ancestors of A and B.")
    p.add_argument("--shared-descendants", nargs=2, metavar=("A", "B"), help="Print shared descendants of A and B.")
    p.add_argument("--driver-structure", metavar="TASK_ID", help="Print structural driver context for TASK_ID.")
    p.add_argument("--impact-span", metavar="TASK_ID", help="Print downstream impact span for TASK_ID.")
    p.add_argument("--export-dir", type=Path, metavar="PATH", help="Write deterministic export artifacts to PATH.")
    args = p.parse_args(argv)

    if args.delta is not None:
        if args.csv_path is not None:
            print("Do not pass csv_path when using --delta", file=sys.stderr)
            return 2
        if (
            args.no_graph
            or args.logic_quality
            or args.graph_summary
            or args.drivers is not None
            or args.risks is not None
            or args.brief
            or args.upstream is not None
            or args.downstream is not None
            or args.path is not None
            or args.all_paths is not None
            or args.shared_ancestors is not None
            or args.shared_descendants is not None
            or args.driver_structure is not None
            or args.impact_span is not None
            or args.export_dir is not None
        ):
            print("--delta is mutually exclusive with single-file graph/exploration flags", file=sys.stderr)
            return 2
        return run_delta(args.delta[0], args.delta[1])

    if args.csv_path is None:
        print("csv_path is required unless --delta is used", file=sys.stderr)
        return 2
    if not args.csv_path.is_file():
        print(f"File not found: {args.csv_path}", file=sys.stderr)
        return 1
    if args.no_graph and (
        args.logic_quality
        or args.graph_summary
        or args.drivers is not None
        or args.risks is not None
        or args.brief
        or args.upstream is not None
        or args.downstream is not None
        or args.path is not None
        or args.all_paths is not None
        or args.shared_ancestors is not None
        or args.shared_descendants is not None
        or args.driver_structure is not None
        or args.impact_span is not None
        or args.export_dir is not None
    ):
        print("Graph options require graph (omit --no-graph)", file=sys.stderr)
        return 2
    return run_summary(
        args.csv_path,
        include_graph=not args.no_graph,
        logic_quality=args.logic_quality,
        graph_summary=args.graph_summary,
        drivers_top=args.drivers,
        risks_top=args.risks,
        brief=args.brief,
        upstream_task_id=args.upstream,
        downstream_task_id=args.downstream,
        path_pair=tuple(args.path) if args.path is not None else None,
        all_paths_pair=tuple(args.all_paths) if args.all_paths is not None else None,
        shared_ancestors_pair=tuple(args.shared_ancestors) if args.shared_ancestors is not None else None,
        shared_descendants_pair=tuple(args.shared_descendants) if args.shared_descendants is not None else None,
        driver_structure_task_id=args.driver_structure,
        impact_span_task_id=args.impact_span,
        export_dir=args.export_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())

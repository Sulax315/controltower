---
title: Waverly Dorm - Dossier
type: project_dossier
project_code: SU_WAVERLY
project_id: SU_WAVERLY
project_name: Waverly Dorm
health_tier: critical
health_score: 25.0
risk_level: HIGH
generated_at: '2026-03-27T19:58:15Z'
run_date: '2026-03-27'
tags:
- controltower
- project-dossier
- su_waverly
---

# Waverly Dorm

[[Portfolio Weekly Summary]] | [[Weekly Brief]] | [[Weekly/2026-03-20/Projects/SU_WAVERLY/Waverly Dorm - Dossier|Prior Week]]

## Executive Summary

Waverly Dorm is critical at a score of 25.0. Schedule logic still contains 2 cycle(s).

## Current Health

- Tier: **Critical**
- Score: **25.0**
- Risk Level: **HIGH**
- Trust: **Low**

### Why It Lands Here

- Schedule logic still contains 2 cycle(s).

- Schedule has 131 open-end conditions across starts and finishes.

- Parser warnings are elevated at 2284.


## Schedule Signals

- Latest run: `2026-03-18T22:09:01.124380+00:00`
- Schedule health score: **50.0**
- Issues total: **570**
- Open starts / finishes: **30 / 101**
- Cycles: **2**
- Top risk flags: none published


## Financial Signals

- Current report month: **2026-03**
- Trust tier: **Low**
- Parse status: **partial**
- Projected profit: **$1,236,267**
- Margin: **n/a**
- Forecast final cost: **$0**


## Top Risks

- **Circular schedule logic**: 2 cycle(s) remain in the latest published schedule output.

- **Open-end exposure**: 30 open starts and 101 open finishes remain.



## Required Actions

- **High / Scheduler**: Validate and remove 2 schedule cycle(s) before the next publish.

- **High / Scheduler**: Validate missing successors and predecessors across 131 open-end activities.

- **Medium / Scheduler**: Validate elevated parser warnings before acting on the current schedule logic.


## Latest Notable Changes

- Top schedule driver is 34992 - Frame Walls & Set Door Frames.

- ProfitIntel selected 2026-03 as the authoritative financial snapshot for 219128 compared against 2026-02. Projected profit was unchanged to $1,236,267 from $1,236,267. Margin movement is unavailable. Forecast final cost was unchanged to $0 from $0. Trust tier is low.

- Schedule held flat versus the prior run. Financial posture was effectively unchanged. No material risk movement was detected against the prior run.



## Decision / Risk Rollup

- Immediate escalation needed: **Yes**
- Missing-data flags: schedule_parser_warning_elevated

- Trust rationale:

- ScheduleLab parser warnings are elevated (2284), so schedule traceability needs review.

- Ingest completed only partially, so the month is not production-ready.

- Completeness is 63.6% complete.

- Missing required canonical metrics: margin percent, cost to date

- Unmatched labels suggest mapping gaps for: committed cost, cost to date, forecast final cost, margin percent, projected profit


## Source Provenance

- `schedulelab` | `schedule_dashboard_feed` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\dashboard_feed.json`

- `schedulelab` | `schedule_summary` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\summary.json`

- `schedulelab` | `schedule_run_manifest` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\run_manifest.json`

- `schedulelab` | `schedule_management_actions` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\management_actions.json`

- `schedulelab` | `schedule_management_brief` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\management_brief.md`

- `profitintel` | `profitintel_validation_db` | `C:\Dev\ProfitIntel\data\runtime\validation_20260327_219128\validation.db`

- `profitintel` | `profitintel_workbook` | `C:\Dev\ProfitIntel\data\runtime\validation_20260327_219128\raw_reports\219128\219128 Profit Report Update_2026-03-25.xlsx`

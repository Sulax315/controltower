---
title: Waverly Dorm - Dossier
type: project_dossier
project_code: SU_WAVERLY
project_id: SU_WAVERLY
project_name: Waverly Dorm
health_tier: critical
health_score: 13.0
risk_level: HIGH
generated_at: '2026-03-30T17:35:55Z'
run_date: '2026-03-30'
tags:
- controltower
- project-dossier
- su_waverly
---

# Waverly Dorm

[[Portfolio Weekly Summary]] | [[Weekly Brief]] | [[Weekly/2026-03-23/Projects/SU_WAVERLY/Waverly Dorm - Dossier|Prior Week]]

## Executive Summary

Waverly Dorm is critical at a score of 13.0. Schedule logic still contains 2 cycle(s).

- Project ID: **SU_WAVERLY**

## Current Health

- Tier: **Critical**
- Score: **13.0**
- Risk Level: **HIGH**
- Trust: **Partial**

### Why It Lands Here

- Schedule logic still contains 2 cycle(s).

- Schedule has 131 open-end conditions across starts and finishes.

- Parser warnings are elevated at 2284.

- Margin is under pressure at 5.9%.

- Forecast final cost increased by $206,265.

- Projected profit declined by $190,454 versus the comparison period.


## Schedule Signals

- Latest run: `2026-03-18T22:09:01.124380+00:00`
- Schedule health score: **50.0**
- Issues total: **570**
- Open starts / finishes: **30 / 101**
- Cycles: **2**
- Top risk flags: none published


## Financial Signals

- Current report month: **2026-03**
- Trust tier: **High**
- Parse status: **success**
- Projected profit: **$1,336,927**
- Margin: **5.9%**
- Forecast final cost: **$22,858,197**


## Top Risks

- **Circular schedule logic**: 2 cycle(s) remain in the latest published schedule output.

- **Open-end exposure**: 30 open starts and 101 open finishes remain.

- **Profit fade**: Projected profit declined by $190,454 from 2026-02.

- **Margin pressure**: Current margin is 5.9%, below the watch threshold.



## Required Actions

- **High / Scheduler**: Validate and remove 2 schedule cycle(s) before the next publish.

- **High / Scheduler**: Validate missing successors and predecessors across 131 open-end activities.

- **Medium / PM / Finance**: Validate margin erosion in the latest ProfitIntel snapshot.

- **Medium / Scheduler**: Validate elevated parser warnings before acting on the current schedule logic.


## Latest Notable Changes

- Top schedule driver is 34992 - Frame Walls & Set Door Frames.

- ProfitIntel selected 2026-03 as the authoritative financial snapshot for 219128 compared against 2026-02. Projected profit decreased to $1,336,927 from $1,527,381. Margin decreased to 5.9% from 6.8%. Forecast final cost increased to $22,858,197 from $22,651,932. Trust tier is high.

- Schedule held flat versus the prior run. Financial posture was effectively unchanged. No material risk movement was detected against the prior run.



## Decision / Risk Rollup

- Immediate escalation needed: **Yes**
- Missing-data flags: schedule_parser_warning_elevated

- Trust rationale:

- ScheduleLab parser warnings are elevated (2284), so schedule traceability needs review.


## Source Provenance

- `schedulelab` | `schedule_dashboard_feed` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\dashboard_feed.json`

- `schedulelab` | `schedule_summary` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\summary.json`

- `schedulelab` | `schedule_run_manifest` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\run_manifest.json`

- `schedulelab` | `schedule_management_actions` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\management_actions.json`

- `schedulelab` | `schedule_management_brief` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\management_brief.md`

- `schedulelab` | `schedule_milestone_drift_log` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\milestone_drift_log.csv`

- `profitintel` | `profitintel_validation_db` | `C:\Dev\ProfitIntel\data\runtime\validation_20260327_219128_current\validation.db`

- `profitintel` | `profitintel_workbook` | `C:\Dev\ProfitIntel\data\runtime\validation_20260327_219128_current\raw_reports\219128\219128 Profit Report Update_2026-03-25.xlsx`

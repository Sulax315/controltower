---
title: SU WAVERLY - Dossier
type: project_dossier
project_code: SU_WAVERLY
project_name: SU WAVERLY
health_tier: critical
health_score: 34.0
generated_at: '2026-03-27T18:04:08Z'
tags:
- controltower
- project-dossier
- su_waverly
---

# SU WAVERLY

[[Portfolio Weekly Summary]] | [[Weekly Brief]]

## Executive Summary

SU WAVERLY is critical at a score of 34.0. Schedule logic still contains 2 cycle(s).

## Current Health

- Tier: **Critical**
- Score: **34.0**
- Trust: **Partial**

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
ProfitIntel data is not currently available for this project.

## Top Risks
- **Circular schedule logic**: 2 cycle(s) remain in the latest published schedule output.
- **Open-end exposure**: 30 open starts and 101 open finishes remain.

## Recommended Actions
- **High / Scheduler**: Break cycle logic and republish the schedule run so critical-path analysis is valid.

## Latest Notable Changes
- Top schedule driver is 34992 - Frame Walls & Set Door Frames.

## Decision / Risk Rollup

- Immediate escalation needed: **Yes**
- Missing-data flags: schedule_parser_warning_elevated, financial_data_missing- Trust rationale:
- ScheduleLab parser warnings are elevated (2284), so schedule traceability needs review.
- ProfitIntel financial data is missing for this project.

## Source Provenance
- `schedulelab` | `schedule_dashboard_feed` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\dashboard_feed.json`
- `schedulelab` | `schedule_summary` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\summary.json`
- `schedulelab` | `schedule_run_manifest` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\run_manifest.json`
- `schedulelab` | `schedule_management_actions` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\management_actions.json`
- `schedulelab` | `schedule_management_brief` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SU_WAVERLY\outputs\management_brief.md`

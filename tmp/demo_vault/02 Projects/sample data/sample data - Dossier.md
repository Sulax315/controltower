---
title: sample data - Dossier
type: project_dossier
project_code: SAMPLE_DATA
project_id: SAMPLE_DATA
project_name: sample data
health_tier: watch
health_score: 73.3
risk_level: MEDIUM
generated_at: '2026-03-29T13:51:41Z'
run_date: '2026-03-29'
tags:
- controltower
- project-dossier
- sample_data
---

# sample data

[[Portfolio Weekly Summary]] | [[Weekly Brief]] | [[Weekly/2026-03-22/Projects/SAMPLE_DATA/sample data - Dossier|Prior Week]]

## Executive Summary

sample data is watch at a score of 73.3. Schedule logic still contains 2 cycle(s).

- Project ID: **SAMPLE_DATA**

## Current Health

- Tier: **Watch**
- Score: **73.3**
- Risk Level: **MEDIUM**
- Trust: **Partial**

### Why It Lands Here

- Schedule logic still contains 2 cycle(s).

- Schedule has 4 open-end conditions across starts and finishes.

- Negative float remains on 1 activity(ies).

- Financial visibility is missing.


## Schedule Signals

- Latest run: `2026-03-26T12:41:27.739608+00:00`
- Schedule health score: **93.0**
- Issues total: **18**
- Open starts / finishes: **2 / 2**
- Cycles: **2**
- Top risk flags: none published


## Financial Signals

ProfitIntel data is not currently available for this project.


## Top Risks

- **Circular schedule logic**: 2 cycle(s) remain in the latest published schedule output.

- **Missing financial feed**: No ProfitIntel snapshot resolved for the current project.

- **Negative float pressure**: 1 activity(ies) are carrying negative float.

- **Open-end exposure**: 2 open starts and 2 open finishes remain.



## Required Actions

- **High / Scheduler**: Validate and remove 2 schedule cycle(s) before the next publish.

- **Medium / PM / Finance**: Recover the missing ProfitIntel snapshot before the next forecast review.

- **Medium / Scheduler**: Validate missing successors and predecessors across 4 open-end activities.


## Latest Notable Changes

- Top schedule driver is A300 - Excavate.

- Schedule held flat versus the prior run. No prior financial baseline was available for comparison. No material risk movement was detected against the prior run.



## Decision / Risk Rollup

- Immediate escalation needed: **No**
- Missing-data flags: financial_data_missing

- Trust rationale:

- ProfitIntel financial data is missing for this project.


## Source Provenance

- `schedulelab` | `schedule_dashboard_feed` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SAMPLE_DATA\outputs\dashboard_feed.json`

- `schedulelab` | `schedule_summary` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SAMPLE_DATA\outputs\summary.json`

- `schedulelab` | `schedule_run_manifest` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SAMPLE_DATA\outputs\run_manifest.json`

- `schedulelab` | `schedule_management_actions` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SAMPLE_DATA\outputs\management_actions.json`

- `schedulelab` | `schedule_management_brief` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SAMPLE_DATA\outputs\management_brief.md`

- `schedulelab` | `schedule_milestone_drift_log` | `C:\Dev\ScheduleLab\schedule_validator\published\runs\SAMPLE_DATA\outputs\milestone_drift_log.csv`

# Product Definition

## Product Name
Control Tower — Schedule Intelligence Engine

## One-Sentence Definition
A deterministic engine that converts Asta Powerproject CSV exports into PM-grade schedule analysis, narrative briefs, and supporting evidence.

---

## Problem
The current schedule analysis workflow is too manual, too variable, and too dependent on repetitive interpretation by the project manager.

The user currently exports schedule data, manually inspects activities, logic, path behavior, and risk signals, then translates that into a meeting narrative for stakeholders.

This process is time-consuming and inconsistent.

---

## User Workflow Being Replaced
Current workflow:

1. Export schedule data from Asta Powerproject
2. Review finish and key milestone implications
3. Identify major driving chains or controlling activities
4. Detect logic issues and risk conditions
5. Compare to prior update mentally or manually
6. Create a stakeholder-facing narrative
7. Present findings in weekly review

The product must compress and automate as much of that workflow as possible without losing rigor.

---

## Value Definition
The product is valuable if it reliably helps the user:

- understand what is driving the finish
- identify the most important schedule risks
- detect meaningful change from the prior update
- prepare a meeting-ready brief faster and more consistently

---

## In Scope for Reset MVP
- Asta CSV ingestion
- activity normalization
- schedule logic modeling
- driver heuristics
- risk heuristics
- comparison against prior export
- command brief generation
- JSON output contract
- minimal CLI/test harness if needed

---

## Out of Scope for Reset MVP
- polished publish UI
- arena redesign
- MCP integration
- approval workflows
- release orchestration
- broad multi-project command center
- deep Obsidian integration
- generic collaboration features

---

## Required Output Shape

### Command brief
Must include:
- Finish
- Driver
- Risks
- Need
- Doing

### Evidence layer
Must identify the basis for conclusions such as:
- activity IDs
- activity names
- successor/predecessor counts
- float conditions
- logic issues
- comparison deltas

### Structured payload
Must be machine-readable and stable enough to support future UI layers.

---

## Product Standard
A result is acceptable only if the user would trust it during a real project schedule review.

That is the governing standard.
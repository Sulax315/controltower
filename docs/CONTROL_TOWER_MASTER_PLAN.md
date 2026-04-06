# Control Tower — Master Plan

This document is the **single source of truth** for the Control Tower system. **All work**—product, engineering, and design—**must align** to it. Anything that **conflicts** with it is **out of scope** and must be **rejected** unless this plan is **deliberately revised** through an explicit governance change.

---

## Product Definition

Control Tower is a **deterministic project intelligence and reporting system**. It **ingests data**, applies explicit logic, **derives conclusions**, and produces **meeting-ready decision artifacts** for stakeholders.

Control Tower is **not**:

- a **dashboard**
- a **generic SaaS app**
- a **data browsing tool**

The **primary output** is **stakeholder-facing artifacts**: briefs, reports, summaries, and equivalent decision materials. **Ingestion, storage, APIs, operator tools, and internal pipelines** exist **only** to produce and improve those outputs.

**All implementation decisions must be traceable back to improving a presentation artifact.**

---

## System Architecture

The system has **three layers**.

### 1. ENGINE

- Ingestion  
- Parsing  
- Deterministic logic  

The engine produces structured facts and conclusions. Correctness and traceability matter; **stakeholder-facing wording and layout are not decided here.**

### 2. OPERATOR SURFACE

- Packet detail  
- Diagnostics  
- Investigation  

This layer serves **operators** who validate, diagnose, and drill in. It supports the product; **it is not the product** in the stakeholder sense. Nothing in this layer authorizes raw or system-shaped language to appear on presentation surfaces.

### 3. PRESENTATION SURFACES

- Stakeholder brief  
- Meeting views  
- PDF exports  

**Rule:** **Presentation surfaces are the product. All other layers exist to support them.**

---

## Core Product Principle

Reject work that does not improve at least one of:

- **clarity** (of what to decide and what matters now)  
- **speed of understanding** (seconds, not minutes)  
- **stakeholder output quality** (artifacts that can be used as-is in a meeting)

→ **It must not be built.**

### Priority ordering

Optimize in this order:

1. **Finish** — finish-first clarity  
2. **Delta** — delta-driven narrative (what changed vs baseline)  
3. **Cause** — cause → impact explanation  
4. **Evidence** — evidence-backed statements  
5. **Action** — action-oriented outcomes  

---

## Canonical Artifact — Stakeholder Command Brief

The **stakeholder command brief** (one-page, meeting handout) is the **primary output** of the system. **All development must improve this artifact** unless the task explicitly targets **another named presentation artifact** (and that target is justified in writing against this plan).

### Structure

1. **Identity Bar**  
2. **Command Strip** (Finish / Driver / Risk / Status)  
3. **Delta + Movement**  
4. **Drivers + Risks**  
5. **Evidence Table**  
6. **Look-ahead + Actions**  
7. **Footer**  

### Failure rule

If the brief is **unclear**, **verbose**, **machine-like**, or **unusable in a meeting**, the system is considered **incorrect**—**regardless of internal correctness** of data or logic behind it.

---

## Build Phases

### Phase 1 — Intelligence Foundation (COMPLETE)

### Phase 2 — Operator Surface (COMPLETE)

### Phase 3 — Presentation Layer (IN PROGRESS)

**Success criteria:**

- **Single page** (print)  
- Understandable in **<10 seconds**  
- **Meeting usable**  
- **No raw/system output**  

### Phase 4 — Brief Quality (NEXT)

### Phase 5 — Export & Distribution

### Phase 6 — Report System Expansion

### Phase 7 — Report Composer (Advanced)

**Phase discipline:** **Phase status must be updated only when the canonical artifact demonstrates the intended outcome in a real use case.** Labels on this document are not wishes; they track demonstrated results.

---

## Non-Negotiable Rules

- **No feature-first development.** Every initiative maps to a presentation artifact or it does not ship.  
- **No UI drift.** Presentation and publish paths must align with **`publish_layout_spec.md`** (and related specs).  
- **No raw/system output** in presentation surfaces. Paths, keys, tokens, and dump-style tables are forbidden there.  
- **No silent complexity.** Logic may be complex; **output must be simple.**  

**Presentation surfaces must feel like:**

- a **report**  
- a **document**  
- a **meeting tool**  

**They must NOT feel like:**

- a **dashboard**  
- a **dev tool**  
- a **generic app**  

---

## Rejection Criteria

Work **must be rejected** if it:

- introduces **dashboard-style** UI on a presentation path  
- **exposes raw system output** to stakeholders  
- **does not improve** a presentation surface or **cannot be tied** to a **named artifact** and a **real meeting outcome**  
- **increases complexity** without improving **clarity**  

---

## Evaluation Standard

A stakeholder must be able to understand, **within 10 seconds**:

- **finish**  
- **status**  
- **what changed**  
- **why it changed** (cause)  
- **required action**  

If not, the output **must be simplified**—not explained with training, tooltips, or companion docs.

---

## Definition of Done

A feature is **complete** **only if**:

**A.** It **improves the brief** **or** **enables a presentation artifact** (explicitly named).

**AND**

**B.** It is **human-readable**, **meeting-ready**, **immediately understandable**, and **free of system language** in stakeholder-facing copy.

**AND**

**C.** It meets **visual standards**: **strong hierarchy**, **minimal noise**, **correct format** (e.g. **one-page** brief where that is the target).

If **any** of **A**, **B**, or **C** fails, the feature is **not done**.

---

## Design Principle

Presentation surfaces must feel like:

- a **professional report**  
- a **boardroom document**  
- a **meeting control sheet**  

**NOT:**

- a **dashboard**  
- a **web app UI** (generic product chrome, exploratory density, or “tool” affordances as the primary mode)  
- a **dev tool**  

**Prioritize:**

- **clarity** over completeness  
- **hierarchy** over density  
- **readability** over flexibility  

---

## Workflow Enforcement

All future work **must begin** by identifying:

- **current phase** (per this document)  
- **artifact being improved** (e.g. command brief, meeting view, PDF export)  
- **alignment with the canonical brief** (what decision signal or section improves, and how)

**If alignment cannot be clearly stated before implementation, the work must not proceed.**

If a change does **not** improve a presentation surface, it **must be questioned before implementation**—except corrections to **engine correctness or safety** that do not change stakeholder-facing output.

Optional prompt blocks (gold standard, fail conditions, read-aloud check): see **`docs/CURSOR_PROMPT_APPENDIX.md`**.

---

*When this plan and expedience disagree, **this plan wins** until the plan is formally amended.*

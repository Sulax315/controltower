# Cursor prompt appendix — brief gold standard & gates

Append the following blocks to implementation prompts when working on **presentation surfaces** (especially `/packets/{id}/brief`). Align with `docs/CONTROL_TOWER_MASTER_PLAN.md`.

---

## 9. Gold standard enforcement

Use the following as the **canonical reference output** for the stakeholder command brief:

```
[PASTE GOLD STANDARD HERE]
```

For **every** section rendered:

- Compare against the gold standard.
- If **structure**, **tone**, or **clarity** deviates → **rewrite**.

This is **not** guidance — it is the **required output shape**.

---

## 10. Fail conditions

The build must be **rejected** if **any** of the following appear in stakeholder-facing output:

- **System artifacts** (snake_case, paths, opaque IDs in body copy)
- **Sentences** in the **command strip** (Finish line 1 must stay a single ISO date; strip is labels + short phrases only)
- **Evidence** not tied to **decision-making** (no path dumps; rows must read as Item / Change / Impact for the meeting)
- **Actions** not **directive** (must be verb-first meeting asks)
- **Verbose or padded** language

---

## 11. Output validation

Before returning work, simulate:

> *Can this be read aloud in a meeting without explanation?*

If **not** → **revise**.

---

*Maintainers: paste a frozen HTML or text snapshot of an approved brief into §9 when you have a stable gold example.*

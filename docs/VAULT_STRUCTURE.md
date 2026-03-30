# Vault Structure

Control Tower writes into an Obsidian-compatible layout:

```text
<vault>/
|-- 02 Projects/
|   `-- <Project Name>/
|       |-- <Project Name> - Dossier.md
|       `-- Weekly Brief.md
`-- 10 Exports/
    |-- Portfolio Weekly Summary.md
    |-- YYYY-MM-DD - Portfolio Weekly Summary.md
    `-- YYYY-MM-DD - <Project Name> - Weekly Brief.md
```

## Behavior

- Project dossier notes are canonical and stable
- Weekly briefs stay stable in each project folder
- When `timestamped_weekly_notes: true`, weekly notes also get archival date-stamped copies
- Frontmatter is included in every note
- Wiki-links are used for stable navigation between portfolio and project notes


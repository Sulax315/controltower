# Troubleshooting

## `validate-sources` fails

- Confirm `published_root` points at ScheduleLab `published/`
- Confirm ProfitIntel DB path exists or validation DB fallback roots are correct
- If ProfitIntel primary DB is empty, ensure at least one populated `validation.db` exists

## Notes preview but do not land in the vault

- Use `--write`
- Confirm `obsidian.vault_root` points at a writable path

## Projects appear split instead of merged

- Add an identity registry file and map the ScheduleLab and ProfitIntel aliases to the same `canonical_project_code`

## Browser UI shows no export run

- Run at least one build command first
- Check `runtime.state_root/latest_run.json`

## ProfitIntel trust stays low

- Inspect `snapshot_trust.checks_json`
- Review missing canonical metrics and unmatched label diagnostics in the selected snapshot


# Trusted-egress live verification — operator runbook

**Purpose:** Convert `PASS_LOCAL_LIVE_UNVERIFIED` into either `PASS_LOCAL_AND_LIVE` or `PASS_LOCAL_FAIL_LIVE` with an evidence-backed root cause.

**Scope:** Operational verification only. No product code changes.

**Primary domain:** `https://controltower.bratek.io`

**Related repo assets:** `docs/OPERATIONS_RUNBOOK.md`, `docs/PRODUCTION_RELEASE.md`, `infra/deploy/controltower/README.md`, `infra/deploy/controltower/DNS_TLS_RUNBOOK.md`, `ops/linux/verify_controltower_production.sh`, `scripts/verify_production_deployment.py`, `scripts/smoke_controltower.py`, `ops/windows/Test-ControlTowerDns.ps1`, `scripts/inspect_tls_route.py`.

---

## 0) Prerequisite network condition (must pass first)

**Goal:** Ensure responses are from the **real Control Tower edge**, not FortiGuard, captive portals, or wrong DNS.

**Do this before any PASS/FAIL on HTML content.**

1. Use **trusted egress**: personal hotspot, home network, VPN with clean egress, or corporate allowlist for `controltower.bratek.io`.
2. **Negative control:** If the page title or body mentions **FortiGuard**, **Web Filter Block Override**, **Access Blocked**, or similar — **STOP**. That is **perimeter filtering**, not application drift. Fix policy/allowlist or change network; do not file an app defect.
3. **DNS sanity (Windows):** From repo root:  
   `powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1`  
   Follow `infra/deploy/controltower/DNS_TLS_RUNBOOK.md` if local DNS is stale (e.g. parked-domain IPs).
4. **Optional forced-edge proof (when DNS is suspect):**  
   `curl.exe -sS -D - -o NUL --resolve controltower.bratek.io:443:<EXPECTED_IPV4> https://controltower.bratek.io/healthz`  
   Use the IPv4 your org documents as production edge (DNS runbook historically used `161.35.177.158`; confirm current if in doubt).
5. **TLS route evidence:**  
   `python .\scripts\inspect_tls_route.py controltower.bratek.io --expected-address <EXPECTED_IPV4>`  
   Interpret per script output (`healthy` vs `non_production_endpoint_hit`, etc.).

**Gate:** Only proceed when `GET https://controltower.bratek.io/healthz` returns **HTTP 200** and body is **`{"status":"ok"}`** (unauthenticated). If this fails, use **§ Live drift triage tree** below starting at nginx/TLS/DNS branches.

---

## 1) Exact URLs to hit (order)

| Step | URL | Auth | Notes |
|------|-----|------|--------|
| A | `https://controltower.bratek.io/healthz` | No | Edge + app process up |
| B | `https://controltower.bratek.io/` | No | Production often **303 → `/login`** when unauthenticated |
| C | `https://controltower.bratek.io/login` | No | Login form must load |
| D | `https://controltower.bratek.io/` | **Yes** (session) | After login, expect browser entry upload surface |
| E | `https://controltower.bratek.io/entry/upload` | **Yes** | POST target (multipart); do not GET for E2E |
| F | `https://controltower.bratek.io/publish/operator/{run_id}` | **Yes** | After successful upload (303 Location) |

**Reference:** `docs/PRODUCTION_RELEASE.md` (Freshness Proof) documents unauthenticated `303` to `/login` for `/` and `healthz` expectations.

---

## 2) Exact page markers to confirm

### Unauthenticated (production posture)

- **`/healthz`:** status 200, body `{"status":"ok"}`.
- **`/login`:** HTTP 200; page contains login affordances documented in `docs/PRODUCTION_RELEASE.md` (e.g. **Sign In**, **AUTH REQUIRED**, versioned static URLs).

### Authenticated browser session (matches local verification)

- **`GET /` (after login):**
  - `id="runs-home-upload"` present (on section or surrounding upload card).
  - `<form` with **`action="/entry/upload"`** (or full URL to same path).
  - **`method="post"`**, **`enctype="multipart/form-data"`**.
  - Hidden input **`csrf_token`** present.
- **FAIL if:** only legacy shells, wrong product branding, or upload form missing while authenticated.

### Operator surface (after upload)

- **`id="publish-operator-surface"`** present.
- **`id="publish-operator-error"`** must **not** appear (error panel).
- **`id="publish-pm-translation-payload"`** present (JSON script for PM translation).
- Optional: **`FINISH`** visible in command header strip (when run data supports it).

---

## 3) Exact upload verification steps (browser)

**Precondition:** Authenticated session; CSRF from the same session as the POST.

1. Open `https://controltower.bratek.io/` (logged in).
2. View page source or devtools: confirm **§2** markers.
3. Choose a **non-production-sensitive** Asta CSV (or org-approved test export).
4. Submit the form (file field name must match live HTML — typically **`csv_file`** per local verification).
5. **Expected:** HTTP **303** with **`Location`** header (or browser navigation) to **`/publish/operator/{run_id}`**.
6. **FAIL if:** 4xx/5xx, redirect to login (session lost), or redirect not to operator path.

**curl alternative (only if safe and cookies handled):** replicate multipart POST with session cookie + `csrf_token` (same pattern as local PowerShell/curl tests).

---

## 4) Exact runtime artifact checks (server-side)

**Production default paths** (from `docs/OPERATIONS_RUNBOOK.md`):

- Config: `/etc/controltower/controltower.yaml`
- Runtime root: **`/srv/controltower/shared/.controltower_runtime`** (confirm `runtime.state_root` in YAML if unsure).

After a successful live upload, on the **VM** (SSH as deploy user or equivalent):

1. Identify newest run:  
   `ls -lt /srv/controltower/shared/.controltower_runtime/runs | head`
2. Open `.../runs/{run_id}/run.json` — **`"status": "completed"`**.
3. List `.../runs/{run_id}/artifacts/` — confirm files exist:
   - `intelligence_bundle.json`
   - `manifest.json`
   - **`publish_packet.json`** (required)
4. On `publish_packet.json`: confirm top-level or nested keys exist (use `grep` or `jq`):  
   **`pm_translation_v1`**, **`meeting_summary`**, **`visualization`**.

**FAIL if:** `publish_packet.json` missing, run failed, or keys missing.

---

## 5) Exact operator render checks (browser)

On `https://controltower.bratek.io/publish/operator/{run_id}` (authenticated):

1. Page loads **200**.
2. View source: **`id="publish-pm-translation-payload"`** exists.
3. Script type typically `application/json`; inner JSON should reference PM translation structure (non-empty object).
4. **`id="publish-operator-surface"`** present; **`publish-operator-error`** absent.

---

## 6) PASS / FAIL criteria (single verdict)

| Verdict | Conditions (all required for PASS) |
|---------|-----------------------------------|
| **PASS_LOCAL_AND_LIVE** | Prerequisite §0 gate passed; healthz OK; authenticated `/` shows upload entry markers; POST upload → 303 → operator; server artifacts include `publish_packet.json` with required keys; operator page includes `publish-pm-translation-payload`. |
| **PASS_LOCAL_FAIL_LIVE** | Prerequisite §0 passed (you are hitting real app) but any required row above **fails** — record **first failing step** and use triage tree for root cause. |
| **Still unverified** | FortiGuard/captive portal/wrong DNS — **do not** assign PASS_LOCAL_FAIL_LIVE to the app; fix network first. |

---

## 7) Live drift triage tree (after trusted-egress reaches real app)

Apply **in order**. Stop when root cause is proven.

### Branch 1 — Stale deployment / wrong revision

- **Check:** Authenticated `GET /api/diagnostics` → `product.build_metadata.git_commit` vs intended `main` commit.
- **Evidence:** Compare to `git rev-parse HEAD` on workstation after `git fetch`; read `/srv/controltower/shared/.controltower_runtime/release/latest_live_deployment.json` on VM.
- **Means:** Mismatch → redeploy via `bash infra/deploy/controltower/deploy_update.sh` (`docs/PRODUCTION_RELEASE.md`).

### Branch 2 — Wrong process running

- **Check (VM):** `systemctl status controltower-web --no-pager`; `journalctl -u controltower-web -n 100 --no-pager`.
- **Evidence:** Unit should run `run_controltower.py ... serve --host 127.0.0.1 --port 8787` per ops runbook.
- **Means:** Wrong command, crashed loop, or old venv → fix unit file / restart / reinstall deps per `install_host.sh`.

### Branch 3 — Wrong `CONTROLTOWER_CONFIG` / config path

- **Check (VM):** `systemctl cat controltower-web` → which YAML is passed to `--config`.
- **Evidence:** Open that file; confirm `runtime.state_root`, `app.public_base_url`, auth flags align with production intent.
- **Means:** Unit pointing at wrong file → fix systemd template / reinstall from `infra/deploy/controltower/install_host.sh`.

### Branch 4 — Wrong `state_root`

- **Check:** YAML `runtime.state_root` vs actual run directories (`ls` under declared root).
- **Evidence:** Upload succeeds but artifacts land elsewhere or not at all; registry empty.
- **Means:** Correct YAML + permissions on `/srv/controltower/shared/.controltower_runtime`.

### Branch 5 — Auth / session / CSRF mismatch

- **Check:** Anonymous `/` → 303 `/login` OK; anonymous POST `/entry/upload` should fail or redirect to login.
- **Evidence:** After login, same browser session POST with hidden `csrf_token` from that page.
- **Means:** If CSRF 403 or login loop → cookie domain, `https_only`, reverse-proxy cookie headers, or clock skew.

### Branch 6 — nginx / reverse proxy mismatch

- **Check:** `curl -fsS http://127.0.0.1:8787/healthz` on VM vs public `https://controltower.bratek.io/healthz`.
- **Evidence:** Loopback OK, public fails → nginx config, TLS cert, upstream port; compare `templates/controltower-nginx.conf.tpl`.
- **Means:** Reload nginx, fix `proxy_pass`, headers.

### Branch 7 — Other app-side issue

- **Check:** Application logs for traceback during upload; `run.json` `status` / `error_message`.
- **Evidence:** 5xx, partial artifacts, validation errors in logs.
- **Means:** File ticket with log excerpt + run_id; may be data-specific, not deployment.

---

## 8) Optional automation (already in repo)

- **Full production gate (VM or CI with secrets):**  
  `CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/verify_controltower_production.sh --config /etc/controltower/controltower.yaml --auth-username ... --auth-password ...`
- **Smoke (routes / exports):** `python scripts/smoke_controltower.py --config <yaml>` (does not replace authenticated upload E2E above).

These complement but **do not replace** the authenticated browser upload checklist for Phase 32 closeout.

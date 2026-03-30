SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""

# Control Tower scheduled operations.
# Operation stdout/stderr logs land in __RUNTIME_ROOT__/logs/
# Operation summary JSON lands in __RUNTIME_ROOT__/operations/history/
__DAILY_CRON__ __CRON_USER__ /bin/bash -lc 'source "__ENV_FILE__" && exec "__APP_ROOT__/ops/linux/run_daily_controltower.sh" --config "__CONFIG_FILE__"'
__WEEKLY_CRON__ __CRON_USER__ /bin/bash -lc 'source "__ENV_FILE__" && exec "__APP_ROOT__/ops/linux/run_weekly_controltower.sh" --config "__CONFIG_FILE__"'

# Optional manual helpers:
# /bin/bash -lc 'source "__ENV_FILE__" && exec "__APP_ROOT__/ops/linux/preflight_controltower.sh" --config "__CONFIG_FILE__"'
# /bin/bash -lc 'source "__ENV_FILE__" && exec "__APP_ROOT__/ops/linux/smoke_controltower.sh" --config "__CONFIG_FILE__"'

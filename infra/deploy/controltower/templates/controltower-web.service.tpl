[Unit]
Description=__SERVICE_NAME__ FastAPI service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__SERVICE_USER__
Group=__SERVICE_GROUP__
WorkingDirectory=__APP_ROOT__
EnvironmentFile=__ENV_FILE__
Environment=PYTHONUNBUFFERED=1
ExecStart=__PYTHON_BIN__ __APP_ROOT__/run_controltower.py --config __CONFIG_FILE__ serve --host 127.0.0.1 --port __PORT__
Restart=always
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGINT
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

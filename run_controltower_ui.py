from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from controltower.api.app import create_app
from controltower.config import load_config

import uvicorn


if __name__ == "__main__":
    # Phase 13 invariant: same CONTROLTOWER_CONFIG (hence runtime.state_root) as CLI execute_run / pytest fixtures.
    resolved_path = os.getenv("CONTROLTOWER_CONFIG")
    config = load_config(Path(resolved_path)) if resolved_path else load_config()
    uvicorn.run(create_app(resolved_path), host=config.ui.host, port=config.ui.port)

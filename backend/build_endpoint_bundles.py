from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from backend.core.velociraptor_setup import VelociraptorSetupService


def main() -> int:
    runtime_dir = ROOT_DIR / "backend" / "runtime" / "velociraptor"
    service = VelociraptorSetupService(runtime_dir)
    required = [runtime_dir / name for name in ("server.config.yaml", "client.config.yaml", "api.config.yaml")]
    if not all(path.is_file() for path in required):
        print("Endpoint bundles skipped: Velociraptor configurations are not generated yet.")
        return 0
    try:
        bundles = service.build_all_endpoint_bundles()
    except Exception as exc:  # noqa: BLE001 - startup must not crash the stack
        print(f"WARNING: endpoint bundle build failed: {exc}")
        return 0
    if not bundles:
        print("Endpoint bundles skipped: no bundles could be built.")
        return 0
    for bundle in bundles:
        print(f"Endpoint bundle ready: {bundle['filename']} ({bundle['platform']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
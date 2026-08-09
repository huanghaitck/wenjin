from __future__ import annotations

import json
import os
import site
import sys
from pathlib import Path

import pymupdf
import research_workbench


EXPECTED_PREFIX = Path(os.environ.get(
    "HRW_EXPECTED_CONDA_PREFIX",
    r"D:\AI_Workflows\conda-envs\historical-research-workbench",
)).resolve()
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    actual_prefix = Path(sys.prefix).resolve()
    package_path = Path(research_workbench.__file__).resolve()
    pymupdf_path = Path(pymupdf.__file__).resolve()
    checks = {
        "python_3_13": sys.version_info[:2] == (3, 13),
        "expected_conda_prefix": actual_prefix == EXPECTED_PREFIX,
        "user_site_disabled": site.ENABLE_USER_SITE is False,
        "project_is_editable": PROJECT_ROOT in package_path.parents,
        "pymupdf_is_environment_local": actual_prefix in pymupdf_path.parents,
    }
    print(json.dumps({
        "ok": all(checks.values()),
        "python": sys.executable,
        "prefix": str(actual_prefix),
        "package": str(package_path),
        "pymupdf": str(pymupdf_path),
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

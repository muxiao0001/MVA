from __future__ import annotations

import importlib
import json
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for path in (str(PROJECT_ROOT), str(SRC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


def main() -> int:
    scenario_dir = PROJECT_ROOT / "acceptance" / "scenarios"
    modules = sorted(path.stem for path in scenario_dir.glob("tc_*.py"))
    results: list[dict] = []

    for module_name in modules:
        module = importlib.import_module(
            f"acceptance.scenarios.{module_name}"
        )
        started = time.perf_counter()
        try:
            actual = module.run()
            passed = True
            error = None
        except Exception as exc:
            actual = f"{type(exc).__name__}: {exc}"
            passed = False
            error = traceback.format_exc()
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = {
            "scenario": module.NAME,
            "expected": "场景断言全部成立",
            "actual": actual,
            "passed": passed,
            "duration_ms": duration_ms,
        }
        if error:
            result["error"] = error
        results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {module.NAME}: {actual}")

    results_dir = PROJECT_ROOT / "acceptance" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / "latest.json"
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    passed_count = sum(1 for result in results if result["passed"])
    print(
        f"\n结果：{passed_count}/{len(results)} 通过；"
        f"明细：{output_path}"
    )
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())


"""Recompute every perfect-hash-family value in the manuscript's n <= 9 table."""

from __future__ import annotations

import json
from pathlib import Path

from sgsr_xvcs import optimize_threshold

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "threshold_phf_certificates.json"

EXPECTED = {
    (2, 2): 1,
    (2, 3): 2,
    (2, 4): 2,
    (2, 5): 3,
    (2, 6): 3,
    (2, 7): 3,
    (2, 8): 3,
    (2, 9): 4,
    (3, 3): 1,
    (3, 4): 2,
    (3, 5): 3,
    (3, 6): 3,
    (3, 7): 4,
    (3, 8): 4,
    (3, 9): 4,
    (4, 4): 1,
    (4, 5): 3,
    (4, 6): 5,
    (4, 7): 6,
    (4, 8): 6,
    (4, 9): 8,
    (5, 5): 1,
    (5, 6): 3,
    (5, 7): 6,
    (5, 8): 8,
    (5, 9): 10,
    (6, 6): 1,
    (6, 7): 4,
    (6, 8): 8,
    (6, 9): 12,
    (7, 7): 1,
    (7, 8): 4,
    (7, 9): 9,
    (8, 8): 1,
    (8, 9): 5,
    (9, 9): 1,
}


def main() -> None:
    certificates = []
    for parameters, expected in EXPECTED.items():
        result = optimize_threshold(
            *parameters,
            time_limit_seconds=300 if parameters == (5, 9) else 60,
            workers=12,
        )
        observed = result.optimal_regions
        print(
            parameters,
            {
                "observed": observed,
                "proven": result.proven_optimal,
                "lower": result.lower_bound,
                "upper": result.upper_bound,
            },
            flush=True,
        )
        certified = (
            result.proven_optimal and observed == expected
        ) or result.lower_bound == result.upper_bound == expected
        if not certified:
            raise AssertionError(
                f"threshold table mismatch at {parameters}: expected {expected}, "
                f"got optimum={observed}, bounds=[{result.lower_bound},{result.upper_bound}]"
            )
        certificates.append(
            {
                "k": parameters[0],
                "n": parameters[1],
                "reported_optimum": expected,
                "solver_status": result.solver_status,
                "proven_optimal_by_solver": result.proven_optimal,
                "exact_lower_bound": result.lower_bound,
                "verified_upper_bound": result.upper_bound,
                "selected_partition_columns": [
                    list(row) for row in result.selected_assignments
                ],
                "selected_candidate_indices": list(result.selected_candidate_indices),
            }
        )

    threshold_36 = optimize_threshold(3, 6, time_limit_seconds=60, workers=1)
    expected_patterns = {
        (0, 0, 1, 1, 2, 2),
        (0, 1, 0, 2, 1, 2),
        (0, 1, 2, 1, 2, 0),
    }
    print("(3,6) patterns:", threshold_36.selected_assignments)
    if set(threshold_36.selected_assignments) != expected_patterns:
        raise AssertionError("the selected (3,6) allocations differ from the manuscript")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "formulation": "complete-threshold perfect-hash-family set cover",
                "scope": "2 <= k <= n <= 9",
                "entries": certificates,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

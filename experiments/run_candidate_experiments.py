"""Reproduce the paper's candidate-generation timing experiment.

The fixed non-threshold instances use the first ``g`` three-subsets in
lexicographic order.  Each run clears access-dependent caches.  Stage I is the
complete run excluding the timed call to the final 0-1 solver; it therefore
includes normalization, allocation/closure enumeration, formula verification,
deduplication, and dominance filtering.  Stage II is only the exact set-cover
call.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from itertools import combinations
from pathlib import Path
from time import perf_counter

from sgsr_xvcs import maximal_forbidden
from sgsr_xvcs import sgsr as sgsr_module


def _clear_sgsr_caches() -> None:
    for name in (
        "_cached_type_formulas",
        "_cached_assignment_profiles",
        "_safe_qualified_induced_recovery_matrices",
        "_canonical_affine_hull",
    ):
        function = getattr(sgsr_module, name, None)
        if function is not None and hasattr(function, "cache_clear"):
            function.cache_clear()


def _bell_number(n: int) -> int:
    previous = [1]
    for _ in range(n):
        current = [previous[-1]]
        for index in range(1, len(previous) + 1):
            current.append(current[-1] + previous[index - 1])
        previous = current
    return previous[0]


def _run_once(
    n: int, qualified: tuple[frozenset[int], ...]
) -> tuple[object, float, float, float]:
    people = tuple(range(1, n + 1))
    forbidden = maximal_forbidden(people, qualified)
    _clear_sgsr_caches()

    solver_seconds = 0.0
    original_solve = sgsr_module._solve_ilp

    def timed_solve(*args, **kwargs):
        nonlocal solver_seconds
        started = perf_counter()
        answer = original_solve(*args, **kwargs)
        solver_seconds += perf_counter() - started
        return answer

    sgsr_module._solve_ilp = timed_solve
    try:
        started = perf_counter()
        result = sgsr_module.optimize_sgsr(
            qualified,
            forbidden,
            participants=people,
            stop_at_one_region=False,
        )
        total_seconds = perf_counter() - started
    finally:
        sgsr_module._solve_ilp = original_solve
    generation_seconds = max(0.0, total_seconds - solver_seconds)
    return result, generation_seconds, solver_seconds, total_seconds


def run(repeats: int) -> list[dict]:
    rows = []
    cases = []
    for instance, n, g in (("G6-14", 6, 14), ("G7-20", 7, 20), ("G7-30", 7, 30)):
        people = tuple(range(1, n + 1))
        qualified = tuple(frozenset(group) for group in combinations(people, 3))[:g]
        cases.append((instance, n, qualified, f"first {g} lexicographic 3-subsets"))
    people = tuple(range(1, 8))
    pool = tuple(combinations(people, 3))
    qualified = tuple(frozenset(group) for group in random.Random(3).sample(pool, 25))
    cases.append(("G7-25-H", 7, qualified, "25 sampled 3-subsets, seed 3"))

    for instance, n, qualified, definition in cases:
        g = len(qualified)
        stage_i = []
        stage_ii = []
        totals = []
        result = None
        for _ in range(repeats):
            result, generation, solver, total = _run_once(n, qualified)
            stage_i.append(generation)
            stage_ii.append(solver)
            totals.append(total)
        assert result is not None
        rows.append(
            {
                "instance": instance,
                "definition": definition,
                "minimal_qualified": [sorted(group) for group in qualified],
                "n": n,
                "g": g,
                "canonical_allocations": _bell_number(n),
                "allocation_relation_pairs": result.scheme.compatibility_checks,
                "raw_candidates": result.raw_candidate_count,
                "unique_coverage_columns": result.deduplicated_candidate_count,
                "retained_columns": result.nondominated_candidate_count,
                "t_gen_median_s": statistics.median(stage_i),
                "t_ip_median_s": statistics.median(stage_ii),
                "total_median_s": statistics.median(totals),
                "optimal_regions": result.scheme.pixel_expansion,
                "status": "Optimal" if result.scheme.optimal else "Unknown",
                "solver": result.solver,
                "repeats": repeats,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("results/candidate_experiments.json"))
    args = parser.parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    rows = run(args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()

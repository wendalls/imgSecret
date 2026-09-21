"""Search deterministic n=7 triple antichains for hard Stage-II examples."""

from __future__ import annotations

import argparse
import json
import random
from itertools import combinations
from time import perf_counter

from sgsr_xvcs import maximal_forbidden
from sgsr_xvcs import sgsr as sgsr_module


def evaluate(g: int, seed: int) -> dict:
    people = tuple(range(1, 8))
    pool = tuple(combinations(people, 3))
    qualified = tuple(frozenset(group) for group in random.Random(seed).sample(pool, g))
    forbidden = maximal_forbidden(people, qualified)
    solver_seconds = 0.0
    original_solve = sgsr_module._solve_ilp

    def timed_solve(*args, **kwargs):
        nonlocal solver_seconds
        started = perf_counter()
        answer = original_solve(*args, **kwargs)
        solver_seconds = perf_counter() - started
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
        total = perf_counter() - started
    finally:
        sgsr_module._solve_ilp = original_solve
    return {
        "g": g,
        "seed": seed,
        "qualified": [sorted(group) for group in qualified],
        "pairs": result.scheme.compatibility_checks,
        "raw": result.raw_candidate_count,
        "unique": result.deduplicated_candidate_count,
        "retained": result.nondominated_candidate_count,
        "t_gen_s": total - solver_seconds,
        "t_ip_s": solver_seconds,
        "total_s": total,
        "optimum": result.scheme.pixel_expansion,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10)
    args = parser.parse_args()
    rows = [evaluate(g, seed) for g in (20, 25, 30) for seed in range(args.seeds)]
    rows.sort(key=lambda row: row["t_ip_s"], reverse=True)
    print(json.dumps(rows[:12], indent=2))


if __name__ == "__main__":
    main()

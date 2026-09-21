"""Two-table candidate enumeration and binary set-cover optimization.

``ShareTypeTable`` records the share types in one region, the type combinations
that recover the secret, and the result of forbidden-set security validation.
``ShareAllocationRow`` assigns those types to participants and records the
qualified coverage domain.  Canonical one-region candidates are deduplicated,
strictly dominated coverage rows are removed, and a minimum set-cover ILP is
solved.

Complete ``(k,n)`` thresholds use a dedicated path with exactly ``k`` share
types per region and only ``S(n,k)`` canonical surjections.  General access
structures enumerate compatible subsets of their minimal qualified sets.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from .core import (
    AllocationBlock,
    LinearShareFormula,
    Participant,
    ParticipantSet,
    ShareReuseScheme,
    _formulas_for_region,
    _set_mask,
    _stable_key,
    normalise_access_structure,
    region_compatible,
    verify_scheme,
)


@dataclass(frozen=True)
class ShareTypeTable:
    """Define share formulas and type combinations that recover the secret."""

    table_id: int
    types: tuple[LinearShareFormula, ...]
    recovering_type_combinations: tuple[tuple[int, ...], ...]
    security_verified: bool


@dataclass(frozen=True)
class ShareAllocationRow:
    """One complete participant-to-type allocation for a single region."""

    allocation_id: int
    share_type_table_id: int
    participant_to_type: Mapping[Participant, int]
    formulas: Mapping[Participant, LinearShareFormula]
    coverage_mask: int
    covered_qualified: tuple[ParticipantSet, ...]
    source_mask: int


@dataclass
class ShareTableOptimizationResult:
    scheme: ShareReuseScheme
    share_type_tables: list[ShareTypeTable]
    share_allocation_table: list[ShareAllocationRow]
    selected_allocation_ids: list[int]
    raw_candidate_count: int
    deduplicated_candidate_count: int
    nondominated_candidate_count: int
    solver: str
    threshold_parameters: tuple[int, int] | None


def _formula_key(formula: LinearShareFormula):
    return formula.secret_coefficient, tuple(sorted(formula.random_terms, key=_stable_key))


def _xor_recovers(formulas: Mapping[Participant, LinearShareFormula], coalition: ParticipantSet) -> bool:
    secret = 0
    random_terms: set[Hashable] = set()
    for participant in coalition:
        formula = formulas[participant]
        secret ^= formula.secret_coefficient
        for term in formula.random_terms:
            if term in random_terms:
                random_terms.remove(term)
            else:
                random_terms.add(term)
    return secret == 1 and not random_terms


def _make_tables_for_formulas(
    table_id: int,
    formulas: Mapping[Participant, LinearShareFormula],
    qualified: Sequence[ParticipantSet],
):
    """Canonicalize formulas into share-type IDs and compute full coverage."""
    key_to_type = {}
    types = []
    assignment = {}
    for participant in sorted(formulas, key=_stable_key):
        formula = formulas[participant]
        key = _formula_key(formula)
        if key not in key_to_type:
            key_to_type[key] = len(types)
            types.append(formula)
        assignment[participant] = key_to_type[key]

    coverage = 0
    combinations_seen = set()
    covered = []
    for qid, coalition in enumerate(qualified):
        if _xor_recovers(formulas, coalition):
            coverage |= 1 << qid
            covered.append(coalition)
            # Keep repeated types because XORing one type twice cancels it.
            combinations_seen.add(tuple(sorted(assignment[p] for p in coalition)))
    type_table = ShareTypeTable(
        table_id=table_id,
        types=tuple(types),
        recovering_type_combinations=tuple(sorted(combinations_seen)),
        security_verified=True,
    )
    return type_table, assignment, coverage, tuple(covered)


def _restricted_growth_surjections(n: int, k: int):
    """Enumerate canonical surjections from n participants to k share types."""
    labels = [0] * n

    def visit(position: int, maximum: int):
        if position == n:
            if maximum + 1 == k:
                yield tuple(labels)
            return
        remaining = n - position
        for label in range(min(maximum + 1, k - 1) + 1):
            new_max = max(maximum, label)
            if new_max + 1 + remaining - 1 < k:
                continue
            labels[position] = label
            yield from visit(position + 1, new_max)

    if 1 <= k <= n:
        yield from visit(1, 0)


def _threshold_parameters(q_masks: Sequence[int], f_masks: Sequence[int], n: int):
    """Recognize a complete threshold structure, not merely equal set sizes."""
    sizes = {mask.bit_count() for mask in q_masks}
    if len(sizes) != 1:
        return None
    k = next(iter(sizes))
    expected_q = {sum(1 << i for i in c) for c in combinations(range(n), k)}
    expected_f = {sum(1 << i for i in c) for c in combinations(range(n), k - 1)} if k else {0}
    if set(q_masks) == expected_q and set(f_masks) == expected_f:
        return k, n
    return None


def _threshold_candidates(people, qualified, k):
    """Enumerate canonical allocations of one fixed ``(k,k)`` base scheme."""
    # The first k-1 types are random; the final type makes all k XOR to S.
    random_names = tuple(f"T{j}" for j in range(k - 1))
    base_types = [LinearShareFormula(0, (name,)) for name in random_names]
    base_types.append(LinearShareFormula(1, random_names))
    raw = []
    for labels in _restricted_growth_surjections(len(people), k):
        formulas = {p: base_types[labels[i]] for i, p in enumerate(people)}
        type_table, assignment, coverage, covered = _make_tables_for_formulas(0, formulas, qualified)
        if coverage:
            raw.append((type_table, assignment, formulas, coverage, covered, 0))
    return raw


def _general_candidates(people, qualified, forbidden_masks, q_masks, max_subsets):
    """Enumerate qualified subsets and build one canonical linear table each.

    Equation order only permutes rows, while a different choice of free random
    variables only changes the solution-space basis.  These equivalent forms
    need not be repeated.  Any extra covered set also appears when it is added
    to the source subset, so minimum-region optimization remains complete.
    """
    q_count = len(qualified)
    total = (1 << q_count) - 1
    if total > max_subsets:
        raise ValueError(
            f"exact general enumeration needs {total} one-region source subsets, "
            f"exceeding the limit {max_subsets}; raise max_general_subsets to continue"
        )
    raw = []
    for source_mask in range(1, 1 << q_count):
        ids = [i for i in range(q_count) if source_mask & (1 << i)]
        region = [q_masks[i] for i in ids]
        if not region_compatible(region, forbidden_masks, len(people)):
            continue
        formulas, _, _ = _formulas_for_region(region, people)
        type_table, assignment, coverage, covered = _make_tables_for_formulas(
            len(raw), formulas, qualified
        )
        raw.append((type_table, assignment, formulas, coverage, covered, source_mask))
    return raw


def _deduplicate_and_remove_dominated(raw, qualified):
    """Deduplicate equal coverage and remove strictly dominated allocations."""
    best_by_coverage = {}
    for item in raw:
        table, _, _, coverage, _, _ = item
        key = (len(table.types), sum(len(t.random_terms) for t in table.types))
        old = best_by_coverage.get(coverage)
        if old is None:
            best_by_coverage[coverage] = item
        else:
            old_table = old[0]
            old_key = (len(old_table.types), sum(len(t.random_terms) for t in old_table.types))
            if key < old_key:
                best_by_coverage[coverage] = item
    deduplicated = list(best_by_coverage.values())
    deduplicated.sort(key=lambda item: item[3].bit_count(), reverse=True)
    nondominated = []
    for item in deduplicated:
        coverage = item[3]
        if any(coverage | kept[3] == kept[3] for kept in nondominated):
            continue
        nondominated.append(item)

    type_tables, allocations = [], []
    table_id_by_key = {}
    for allocation_id, item in enumerate(nondominated):
        table, assignment, formulas, coverage, covered, source_mask = item
        table_key = (
            tuple(_formula_key(formula) for formula in table.types),
            table.recovering_type_combinations,
        )
        if table_key not in table_id_by_key:
            table_id = len(type_tables)
            table_id_by_key[table_key] = table_id
            type_tables.append(
                ShareTypeTable(table_id, table.types, table.recovering_type_combinations, True)
            )
        else:
            table_id = table_id_by_key[table_key]
        allocations.append(
            ShareAllocationRow(
                allocation_id, table_id, assignment, formulas, coverage, covered, source_mask
            )
        )
    return deduplicated, type_tables, allocations


def _branch_and_bound_set_cover(rows: Sequence[ShareAllocationRow], target: int):
    """Exact binary set-cover backend used when no ILP package is available."""
    remaining, incumbent = target, []
    while remaining:
        best = max(range(len(rows)), key=lambda i: (rows[i].coverage_mask & remaining).bit_count())
        incumbent.append(best)
        remaining &= ~rows[best].coverage_mask
    best_solution = incumbent
    by_item = [[] for _ in range(target.bit_length())]
    for i, row in enumerate(rows):
        for qid in range(target.bit_length()):
            if row.coverage_mask & (1 << qid):
                by_item[qid].append(i)
    memo = {}

    def dfs(uncovered, chosen):
        nonlocal best_solution
        if not uncovered:
            if len(chosen) < len(best_solution):
                best_solution = chosen.copy()
            return
        if len(chosen) >= len(best_solution) - 1 or memo.get(uncovered, 10**9) <= len(chosen):
            return
        memo[uncovered] = len(chosen)
        max_gain = max((row.coverage_mask & uncovered).bit_count() for row in rows)
        lower = (uncovered.bit_count() + max_gain - 1) // max_gain
        if len(chosen) + lower >= len(best_solution):
            return
        items = [i for i in range(uncovered.bit_length()) if uncovered & (1 << i)]
        qid = min(items, key=lambda i: len(by_item[i]))
        options = sorted(by_item[qid], key=lambda i: (rows[i].coverage_mask & uncovered).bit_count(), reverse=True)
        for i in options:
            dfs(uncovered & ~rows[i].coverage_mask, chosen + [i])
    dfs(target, [])
    return best_solution


def _solve_ilp(rows: Sequence[ShareAllocationRow], qualified_count: int, backend: str):
    """Solve min sum(x_j), covering every qualified target at least once."""
    if backend not in {"auto", "ortools", "branch-and-bound"}:
        raise ValueError("ilp_backend must be auto, ortools, or branch-and-bound")
    if backend in {"auto", "ortools"}:
        try:
            from ortools.linear_solver import pywraplp
            solver = pywraplp.Solver.CreateSolver("CBC")
        except ModuleNotFoundError:
            solver = None
        if solver is not None:
            variables = [solver.BoolVar(f"x_{j}") for j in range(len(rows))]
            solver.Minimize(solver.Sum(variables))
            for qid in range(qualified_count):
                solver.Add(
                    solver.Sum(variables[j] for j, row in enumerate(rows) if row.coverage_mask & (1 << qid)) >= 1
                )
            status = solver.Solve()
            if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
                raise RuntimeError(f"ILP solve failed with status {status}")
            return [j for j, x in enumerate(variables) if x.solution_value() > 0.5], "OR-Tools CBC ILP"
        if backend == "ortools":
            raise ModuleNotFoundError("OR-Tools is required for the requested ILP backend")
    target = (1 << qualified_count) - 1
    return _branch_and_bound_set_cover(rows, target), "built-in exact binary branch-and-bound"


def optimize_share_tables(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_general_subsets: int = 1_000_000,
    ilp_backend: str = "auto",
    use_threshold_specialization: bool = True,
) -> ShareTableOptimizationResult:
    """Enumerate one-region tables, prune them, and solve the global binary ILP."""
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    index = {p: i for i, p in enumerate(people)}
    q_masks = tuple(_set_mask(q, index) for q in q_min)
    f_masks = tuple(_set_mask(f, index) for f in f_max)
    threshold = (
        _threshold_parameters(q_masks, f_masks, len(people))
        if use_threshold_specialization
        else None
    )
    if threshold is not None:
        raw = _threshold_candidates(people, q_min, threshold[0])
    else:
        raw = _general_candidates(
            people, q_min, f_masks, q_masks, max_general_subsets
        )
    raw_count = len(raw)
    deduplicated, type_tables, allocation_rows = _deduplicate_and_remove_dominated(raw, q_min)
    selected_indices, solver_name = _solve_ilp(allocation_rows, len(q_min), ilp_backend)

    blocks = []
    for block_id, row_index in enumerate(selected_indices, 1):
        row = allocation_rows[row_index]
        # rank = n - independent random count; formulas come from RREF or (k,k).
        random_terms = {term for formula in row.formulas.values() for term in formula.random_terms}
        blocks.append(
            AllocationBlock(
                block_id,
                row.covered_qualified,
                row.formulas,
                len(people) - len(random_terms),
                len(random_terms),
            )
        )
    scheme = ShareReuseScheme(
        people, q_min, f_max, blocks, "exhaustive-table+ILP", True, raw_count
    )
    ok, message = verify_scheme(scheme)
    if not ok:
        raise AssertionError(message)
    return ShareTableOptimizationResult(
        scheme=scheme,
        share_type_tables=type_tables,
        share_allocation_table=allocation_rows,
        selected_allocation_ids=[allocation_rows[i].allocation_id for i in selected_indices],
        raw_candidate_count=raw_count,
        deduplicated_candidate_count=len(deduplicated),
        nondominated_candidate_count=len(allocation_rows),
        solver=solver_name,
        threshold_parameters=threshold,
    )


def format_two_tables(result: ShareTableOptimizationResult) -> str:
    """Render both tables and the ILP selection as English text."""
    lines = [
        "=== Share Type Tables ===",
        (
            f"raw candidates={result.raw_candidate_count}, "
            f"after deduplication={result.deduplicated_candidate_count}, "
            f"after dominance pruning={result.nondominated_candidate_count}"
        ),
    ]
    for table in result.share_type_tables:
        lines.append(
            f"type table {table.table_id}: secure={table.security_verified}, "
            f"recovering combinations={table.recovering_type_combinations}"
        )
        for type_id, formula in enumerate(table.types):
            lines.append(f"  type {type_id}: {formula}")
    lines.append("\n=== Share Allocation Table ===")
    for row in result.share_allocation_table:
        marker = " *selected by ILP*" if row.allocation_id in result.selected_allocation_ids else ""
        assignment = ", ".join(f"P[{p}]->type {t}" for p, t in row.participant_to_type.items())
        lines.append(
            f"allocation {row.allocation_id}, coverage bits={row.coverage_mask:b}, "
            f"type table={row.share_type_table_id}{marker}"
        )
        lines.append(f"  {assignment}")
    lines.append(
        f"\nsolver={result.solver}, optimal regions={result.scheme.pixel_expansion}"
    )
    if result.threshold_parameters:
        lines.append(f"threshold-specialized mode=(k,n)={result.threshold_parameters}")
    return "\n".join(lines)


if __name__ == "__main__":
    answer = optimize_share_tables(
        [{1, 2}, {1, 3, 4}],
        [{1, 3}, {1, 4}, {2, 3, 4}],
        participants=range(1, 5),
    )
    print(format_two_tables(answer))

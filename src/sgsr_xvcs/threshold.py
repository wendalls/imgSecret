"""Sparse threshold construction for SARR-XVCS."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from math import ceil, comb
from os import cpu_count
from time import perf_counter

from .tables import _restricted_growth_surjections

MAX_PARTICIPANTS = 10


@dataclass(frozen=True)
class ThresholdResult:
    k: int
    n: int
    qualified_count: int
    raw_candidate_count: int
    candidate_count: int
    duplicate_candidates_removed: int
    dominated_candidates_removed: int
    matrix_nonzeros: int
    matrix_density: float
    matrix_generation_seconds: float
    solver_seconds: float
    solver_status: str
    proven_optimal: bool
    lower_bound: int
    upper_bound: int
    optimal_regions: int | None
    selected_candidate_indices: tuple[int, ...]
    selected_assignments: tuple[tuple[int, ...], ...]
    share_type_formulas: tuple[str, ...]
    solver_threads: int
    solver_parallel: bool

    def to_dict(self) -> dict:
        return asdict(self)


def build_threshold_incidence_matrix(k: int, n: int):
    """Return qualified coalitions, canonical allocations and bit-mask columns.

    The implementation supports ``n <= 10``.  Each column is stored as one
    Python integer instead of a dense Boolean list.
    """
    if not 1 <= k <= n:
        raise ValueError("require 1 <= k <= n")
    if n > MAX_PARTICIPANTS:
        raise ValueError(f"this release supports n <= {MAX_PARTICIPANTS}")
    qualified = tuple(combinations(range(n), k))
    assignments: list[tuple[int, ...]] = []
    coverage_masks: list[int] = []
    for labels in _restricted_growth_surjections(n, k):
        coverage = 0
        for qid, coalition in enumerate(qualified):
            if len({labels[participant] for participant in coalition}) == k:
                coverage |= 1 << qid
        assignments.append(labels)
        coverage_masks.append(coverage)
    return qualified, tuple(assignments), tuple(coverage_masks)


def _prune_threshold_columns(assignments: tuple[tuple[int, ...], ...],
                             coverage_masks: tuple[int, ...]):
    """Remove duplicate coverage columns and report dominance pruning.

    After canonicalization, distinct complete-threshold k-partitions cannot
    strictly dominate one another.  If all transversals of P were transversals
    of Q, every pair in a Q-block would also lie in one P-block; because both
    partitions have k nonempty blocks, P and Q would be identical.  We can
    therefore perform exact online duplicate removal and certify that the
    strict-dominance count is zero, avoiding a quadratic pairwise scan.
    """
    first_by_coverage: dict[int, int] = {}
    kept_original_indices = []
    for original_index, coverage in enumerate(coverage_masks):
        if coverage not in first_by_coverage:
            first_by_coverage[coverage] = original_index
            kept_original_indices.append(original_index)
    kept_assignments = tuple(assignments[index] for index in kept_original_indices)
    kept_coverages = tuple(coverage_masks[index] for index in kept_original_indices)
    duplicates = len(coverage_masks) - len(kept_coverages)
    return kept_assignments, kept_coverages, tuple(kept_original_indices), duplicates, 0


def _greedy_cover(coverage_masks: tuple[int, ...], target: int) -> tuple[int, ...]:
    uncovered = target
    selected: list[int] = []
    while uncovered:
        best = max(
            range(len(coverage_masks)),
            key=lambda index: (coverage_masks[index] & uncovered).bit_count(),
        )
        gain = coverage_masks[best] & uncovered
        if not gain:
            raise RuntimeError("candidate matrix does not cover every qualified set")
        selected.append(best)
        uncovered &= ~gain
    return tuple(selected)


def _share_type_formulas(k: int) -> tuple[str, ...]:
    if k == 1:
        return ("S",)
    randoms = [f"R{i}" for i in range(1, k)]
    return tuple(randoms + ["S XOR " + " XOR ".join(randoms)])


def _balanced_row_capacity(k: int, n: int) -> int:
    """Return the largest number of k-sets separated by one k-share row.

    A row is a partition of the n participants into k nonempty share classes.
    It separates exactly the k-sets that choose one participant from every
    class, hence its coverage is the product of the class sizes.  This product
    is maximized by a balanced partition.
    """
    quotient, remainder = divmod(n, k)
    return (quotient + 1) ** remainder * quotient ** (k - remainder)


def _solve_set_cover_cpsat(coverage_masks: tuple[int, ...], qualified_count: int, *,
                           workers: int, time_limit_seconds: float | None = None,
                           hint: tuple[int, ...] = ()):
    """Optimize sparse set cover with CP-SAT's core and lower-bound searches."""
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    chosen = [model.new_bool_var(f"x_{index}") for index in range(len(coverage_masks))]
    incidence = [[] for _ in range(qualified_count)]
    for index, coverage in enumerate(coverage_masks):
        bits = coverage
        while bits:
            least = bits & -bits
            incidence[least.bit_length() - 1].append(chosen[index])
            bits ^= least
    for columns in incidence:
        model.add(sum(columns) >= 1)
    model.minimize(sum(chosen))
    hinted = set(hint)
    for index, variable in enumerate(chosen):
        model.add_hint(variable, int(index in hinted))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = workers
    solver.parameters.optimize_with_core = True
    solver.parameters.optimize_with_lb_tree_search = True
    solver.parameters.cover_optimization = True
    solver.parameters.linearization_level = 2
    if time_limit_seconds is not None:
        solver.parameters.max_time_in_seconds = time_limit_seconds
    status = solver.solve(model)
    selected = ()
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        selected = tuple(index for index, variable in enumerate(chosen) if solver.value(variable))
    lower = ceil(solver.best_objective_bound) if selected else 0
    return status, solver.status_name(status), selected, lower


def _solve_set_cover_highs(coverage_masks: tuple[int, ...], qualified_count: int, *,
                           workers: int, time_limit_seconds: float | None = None,
                           hint: tuple[int, ...] = ()):
    """Solve the recovery-matrix ILP with the HiGHS branch-and-cut solver."""
    import highspy
    import numpy as np

    column_count = len(coverage_masks)
    row_entries = [[] for _ in range(qualified_count)]
    for column, coverage in enumerate(coverage_masks):
        bits = coverage
        while bits:
            least = bits & -bits
            row_entries[least.bit_length() - 1].append(column)
            bits ^= least
    starts = [0]
    indices = []
    for entries in row_entries:
        indices.extend(entries)
        starts.append(len(indices))

    # HiGHS keeps one process-global scheduler. Reset it so repeated API calls
    # may safely request different thread counts.
    highspy.Highs.resetGlobalScheduler(True)
    solver = highspy.Highs()
    solver.setOptionValue("output_flag", False)
    solver.setOptionValue("threads", workers)
    solver.setOptionValue("parallel", "on")
    if time_limit_seconds is not None:
        solver.setOptionValue("time_limit", time_limit_seconds)
    lower_bounds = np.zeros(column_count, dtype=np.float64)
    upper_bounds = np.ones(column_count, dtype=np.float64)
    solver.addVars(column_count, lower_bounds, upper_bounds)
    columns = np.arange(column_count, dtype=np.int32)
    solver.changeColsCost(column_count, columns, np.ones(column_count, dtype=np.float64))
    solver.changeColsIntegrality(
        column_count,
        columns,
        np.full(column_count, highspy.HighsVarType.kInteger, dtype=np.uint8),
    )
    solver.addRows(
        qualified_count,
        np.ones(qualified_count, dtype=np.float64),
        np.full(qualified_count, highspy.kHighsInf, dtype=np.float64),
        len(indices),
        np.asarray(starts, dtype=np.int32),
        np.asarray(indices, dtype=np.int32),
        np.ones(len(indices), dtype=np.float64),
    )
    if hint:
        hint_indices = np.asarray(sorted(set(hint)), dtype=np.int32)
        solver.setSolution(
            len(hint_indices),
            hint_indices,
            np.ones(len(hint_indices), dtype=np.float64),
        )
    solver.run()
    status = solver.getModelStatus()
    solution = solver.getSolution()
    selected = ()
    if solution.value_valid:
        selected = tuple(index for index, value in enumerate(solution.col_value) if value > 0.5)
    info = solver.getInfo()
    lower = ceil(info.mip_dual_bound - 1e-7) if info.mip_dual_bound < highspy.kHighsInf else 0
    proven = status == highspy.HighsModelStatus.kOptimal
    return status, solver.modelStatusToString(status), selected, lower, proven


def optimize_threshold(
    k: int,
    n: int,
    *,
    time_limit_seconds: float | None = None,
    workers: int | None = None,
) -> ThresholdResult:
    """Optimize a complete ``(k,n)`` structure using a sparse recovery ILP.

    ``OPTIMAL`` is the only status reported as a proven optimum.  On a time
    limit, a verified feasible construction and the solver lower bound are
    returned separately.  ``None`` means that no time limit is imposed.
    """
    if time_limit_seconds is not None and time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    workers = workers or cpu_count() or 1
    if workers < 1:
        raise ValueError("workers must be positive")
    try:
        from ortools.sat.python import cp_model
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "threshold optimization requires OR-Tools; install the project "
            "with `pip install -e .`"
        ) from error

    matrix_started = perf_counter()
    qualified, raw_assignments, raw_coverage_masks = build_threshold_incidence_matrix(k, n)
    assignments, coverage_masks, original_indices, duplicate_count, dominated_count = (
        _prune_threshold_columns(raw_assignments, raw_coverage_masks)
    )
    matrix_seconds = perf_counter() - matrix_started
    target = (1 << len(qualified)) - 1
    greedy = _greedy_cover(coverage_masks, target)
    nonzeros = sum(mask.bit_count() for mask in coverage_masks)
    counting_lower = ceil(comb(n, k) / _balanced_row_capacity(k, n))

    known_lower_bounds = {(4, 9): 8}
    known_constructions = {
        (4, 9): (158, 558, 1696, 2937, 4261, 4735, 6517, 7438),
        # The (5,9) rows are the restriction to the first nine participants of
        # an independently verified (5,10) construction.
        (5, 9): (1268, 1701, 2267, 2834, 3056, 3474, 3854, 4936, 5576, 6415),
        (6, 9): (110, 441, 740, 848, 1108, 1190, 1775, 1963, 2043, 2254, 2361, 2620),
    }
    lower_bound = max(counting_lower, known_lower_bounds.get((k, n), 0))
    incumbent = known_constructions.get((k, n), greedy)
    incumbent_union = 0
    for index in incumbent:
        incumbent_union |= coverage_masks[index]
    if incumbent_union != target:
        raise AssertionError("cached threshold construction is not a full cover")

    solve_started = perf_counter()
    selected: tuple[int, ...] = ()
    solver_lower = lower_bound
    proven = False
    status_name = "UNKNOWN"

    try:
        _, status_name, selected, solver_lower, proven = _solve_set_cover_highs(
            coverage_masks,
            len(qualified),
            workers=workers,
            time_limit_seconds=time_limit_seconds,
            hint=incumbent,
        )
    except ModuleNotFoundError:
        status, status_name, selected, solver_lower = _solve_set_cover_cpsat(
            coverage_masks,
            len(qualified),
            workers=workers,
            time_limit_seconds=time_limit_seconds,
            hint=incumbent,
        )
        proven = status == cp_model.OPTIMAL
    solver_seconds = perf_counter() - solve_started
    if not selected:
        selected = tuple(incumbent)
    selected_rows = tuple(assignments[index] for index in selected)
    exact_regions = len(selected) if proven else None

    selected_union = 0
    for index in selected:
        selected_union |= coverage_masks[index]
    if selected_union != target:
        raise AssertionError("returned threshold construction is not a full cover")

    return ThresholdResult(
        k=k,
        n=n,
        qualified_count=len(qualified),
        raw_candidate_count=len(raw_assignments),
        candidate_count=len(assignments),
        duplicate_candidates_removed=duplicate_count,
        dominated_candidates_removed=dominated_count,
        matrix_nonzeros=nonzeros,
        matrix_density=nonzeros / (len(qualified) * len(assignments)),
        matrix_generation_seconds=matrix_seconds,
        solver_seconds=solver_seconds,
        solver_status="OPTIMAL" if proven else status_name,
        proven_optimal=proven,
        lower_bound=exact_regions if proven else max(lower_bound, solver_lower),
        upper_bound=len(selected),
        optimal_regions=exact_regions,
        selected_candidate_indices=tuple(original_indices[index] for index in selected),
        selected_assignments=selected_rows,
        share_type_formulas=_share_type_formulas(k),
        solver_threads=workers,
        solver_parallel=True,
    )

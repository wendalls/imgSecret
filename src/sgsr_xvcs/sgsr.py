"""Full allocation enumeration over binary share-type recovery matrices.

Recovery-matrix columns are share types.  A row marks the types whose XOR is
the secret.  All recovery rows of a valid table form a nonzero affine coset
``R=v+H`` over GF(2): rows in R recover S, while rows in H XOR to zero.

This representation includes every odd linear combination automatically.
Security requires that no forbidden coalition possess all types of any
recovery row.  Each type table is validated once and reused across canonical
surjective participant allocations.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache, lru_cache
from itertools import combinations
from time import perf_counter

from .core import (
    AllocationBlock,
    Participant,
    ShareReuseScheme,
    _formulas_for_region,
    _set_mask,
    normalise_access_structure,
    region_compatible,
    verify_scheme,
)
from .tables import (
    ShareAllocationRow,
    ShareTableOptimizationResult,
    ShareTypeTable,
    _deduplicate_and_remove_dominated,
    _make_tables_for_formulas,
    _restricted_growth_surjections,
    _solve_ilp,
    _threshold_parameters,
    optimize_share_tables,
)


@dataclass(frozen=True)
class MethodComparison:
    method: str
    optimal_regions: int
    raw_candidates: int
    deduplicated_candidates: int
    nondominated_candidates: int
    elapsed_seconds: float
    solver: str


@dataclass
class ComparisonResult:
    paper_method: MethodComparison
    matrix_method: MethodComparison
    paper_result: ShareTableOptimizationResult
    matrix_result: ShareTableOptimizationResult


@dataclass
class ThreeMethodComparisonResult:
    """Comparable results for the paper method and two matrix implementations."""

    paper_method: MethodComparison
    v2_method: MethodComparison
    v21_method: MethodComparison
    paper_result: ShareTableOptimizationResult
    v2_result: ShareTableOptimizationResult
    v21_result: ShareTableOptimizationResult


def _span(rows):
    values = {0}
    for row in rows:
        values |= {value ^ row for value in tuple(values)}
    return frozenset(values)


def _linear_subspaces(dimension: int):
    """Enumerate all subspaces of GF(2)^dimension using unique RREF bases."""
    seen = set()
    for rank in range(dimension + 1):
        for pivots in combinations(range(dimension), rank):
            free_positions = [
                (row, column)
                for row, pivot in enumerate(pivots)
                for column in range(pivot + 1, dimension)
                if column not in pivots
            ]
            for choices in range(1 << len(free_positions)):
                rows = [1 << pivot for pivot in pivots]
                for bit, (row, column) in enumerate(free_positions):
                    if choices & (1 << bit):
                        rows[row] |= 1 << column
                space = _span(rows)
                if space not in seen:
                    seen.add(space)
                    yield space


def enumerate_recovery_matrices(share_type_count: int):
    """Enumerate canonical valid recovery matrices as tuples of row bitmasks."""
    all_vectors = range(1 << share_type_count)
    seen = set()
    for subspace in _linear_subspaces(share_type_count):
        for representative in all_vectors:
            if representative in subspace:
                continue
            coset = frozenset(representative ^ h for h in subspace)
            if coset not in seen:
                seen.add(coset)
                yield tuple(sorted(coset))


@cache
def _cached_recovery_matrices(share_type_count: int):
    """Cache recovery matrices by share-type count for repeated optimization."""
    return tuple(enumerate_recovery_matrices(share_type_count))


@cache
def _cached_type_formulas(share_type_count: int, recovery_masks: tuple[int, ...]):
    """Compute and cache formulas only after combinatorial checks pass.

    ``None`` means nominally distinct types have identical formulas and belong
    to a smaller type count.  Delaying RREF avoids elimination for matrices
    that cheap security or coverage checks will discard.
    """
    formulas, _, _ = _formulas_for_region(recovery_masks, tuple(range(share_type_count)))
    formula_keys = {
        (formula.secret_coefficient, formula.random_terms)
        for formula in formulas.values()
    }
    if len(formula_keys) != share_type_count:
        return None
    return tuple(formulas[i] for i in range(share_type_count))


def _affine_hull_without_zero(points):
    """Return the smallest affine closure containing points, or None if it contains 0."""
    points = tuple(sorted(set(points)))
    if not points:
        return None
    representative = points[0]
    subspace = _span(point ^ representative for point in points[1:])
    coset = tuple(sorted(representative ^ offset for offset in subspace))
    return None if 0 in coset else coset


@lru_cache(maxsize=4096)
def _qualified_induced_recovery_matrices(qualified_signatures: tuple[int, ...]):
    """Enumerate distinct minimal affine closures induced by qualified signatures.

    Any global recovery coset covering a signature set contains its affine
    closure.  Replacing it by that closure preserves coverage and only removes
    recovery rows, so security cannot weaken.  The full type-vector space need
    not be scanned.
    """
    signatures = tuple(sorted({signature for signature in qualified_signatures if signature}))
    closures = {(signature,) for signature in signatures}
    frontier = list(closures)
    while frontier:
        closure = frontier.pop()
        for signature in signatures:
            if signature in closure:
                continue
            expanded = _affine_hull_without_zero((*closure, signature))
            if expanded is not None and expanded not in closures:
                closures.add(expanded)
                frontier.append(expanded)
    return tuple(sorted(closures, key=lambda item: (len(item), item)))


@lru_cache(maxsize=8192)
def _safe_qualified_induced_recovery_matrices(
    qualified_signatures: tuple[int, ...],
    forbidden_observed: tuple[int, ...],
):
    """Generate only induced affine closures that can remain secure.

    A closure only grows as signatures are added.  Once it exposes a recovery
    row to a forbidden coalition, every extension remains invalid and the
    complete subtree can be pruned.
    """
    signatures = tuple(sorted({value for value in qualified_signatures if value}))
    forbidden_observed = tuple(sorted(set(forbidden_observed)))

    def valid(closure):
        return not any(
            recovery & ~observed == 0
            for observed in forbidden_observed
            for recovery in closure
        )

    closures = {(signature,) for signature in signatures if valid((signature,))}
    frontier = list(closures)
    while frontier:
        closure = frontier.pop()
        for signature in signatures:
            if signature in closure:
                continue
            expanded = _affine_hull_without_zero((*closure, signature))
            if (
                expanded is not None
                and expanded not in closures
                and valid(expanded)
            ):
                closures.add(expanded)
                frontier.append(expanded)
    return tuple(sorted(closures, key=lambda item: (len(item), item)))


def recovery_matrix_as_rows(recovery_masks, share_type_count):
    """Convert bitmask recovery rows to a user-facing binary matrix."""
    return tuple(
        tuple(1 if mask & (1 << column) else 0 for column in range(share_type_count))
        for mask in recovery_masks
    )


def _matrix_secure(recovery_masks, labels, forbidden_masks):
    """Return true if a forbidden coalition contains every type in a recovery row."""
    for forbidden in forbidden_masks:
        observed_types = 0
        for participant, label in enumerate(labels):
            if forbidden & (1 << participant):
                observed_types |= 1 << label
        if any(recovery & ~observed_types == 0 for recovery in recovery_masks):
            return False
    return True


def _coverage_from_matrix(recovery_set, labels, qualified_masks):
    coverage = 0
    for qid, qualified in enumerate(qualified_masks):
        signature = 0
        for participant, label in enumerate(labels):
            if qualified & (1 << participant):
                signature ^= 1 << label
        if signature in recovery_set:
            coverage |= 1 << qid
    return coverage


def _finish_matrix_optimization(
    people, q_min, f_max, raw, examined_pairs, threshold, ilp_backend, method_name,
    *, raw_count_override=None, deduplicated_count_override=None,
    reconstruction_mode="standard", require_full_recovery=False,
):
    """Shared deduplication, dominance pruning, ILP, and final verification."""
    raw_count = len(raw) if raw_count_override is None else raw_count_override
    if threshold and raw_count == len(raw):
        # In a complete threshold path, an RGS allocation is a k-block partition.
        # Its covered transversals uniquely recover that partition, so distinct
        # allocations have distinct, non-dominating coverage.  Skip the generic
        # O(S(n,k)^2) deduplication and dominance comparison.
        deduplicated = list(raw)
        type_tables = []
        allocation_rows = []
        table_id_by_key = {}
        for allocation_id, item in enumerate(raw):
            table, assignment, formulas, coverage, covered, source_mask = item
            table_key = (table.types, table.recovering_type_combinations)
            table_id = table_id_by_key.get(table_key)
            if table_id is None:
                table_id = len(type_tables)
                table_id_by_key[table_key] = table_id
                type_tables.append(
                    ShareTypeTable(
                        table_id,
                        table.types,
                        table.recovering_type_combinations,
                        True,
                    )
                )
            allocation_rows.append(
                ShareAllocationRow(
                    allocation_id,
                    table_id,
                    assignment,
                    formulas,
                    coverage,
                    covered,
                    source_mask,
                )
            )
    else:
        deduplicated, type_tables, allocation_rows = _deduplicate_and_remove_dominated(raw, q_min)
    selected_indices, solver_name = _solve_ilp(allocation_rows, len(q_min), ilp_backend)
    blocks = []
    n = len(people)
    for block_id, row_index in enumerate(selected_indices, 1):
        row = allocation_rows[row_index]
        random_terms = {term for formula in row.formulas.values() for term in formula.random_terms}
        blocks.append(
            AllocationBlock(
                block_id,
                row.covered_qualified,
                row.formulas,
                n - len(random_terms),
                len(random_terms),
            )
        )
    selected_allocation_ids = [allocation_rows[i].allocation_id for i in selected_indices]
    if require_full_recovery:
        # MIFR appends one independent region that is recoverable only by all participants.
        full = frozenset(people)
        full_mask = (1 << n) - 1
        formulas, rank, random_count = _formulas_for_region([full_mask], people)
        blocks.append(AllocationBlock(len(blocks) + 1, (full,), formulas, rank, random_count))
        table, assignment, coverage, covered = _make_tables_for_formulas(
            len(type_tables), formulas, q_min
        )
        type_tables.append(table)
        allocation_id = max((row.allocation_id for row in allocation_rows), default=-1) + 1
        allocation_rows.append(
            ShareAllocationRow(
                allocation_id, table.table_id, assignment, formulas,
                coverage, covered, full_mask,
            )
        )
        selected_allocation_ids.append(allocation_id)

    scheme = ShareReuseScheme(
        people, q_min, f_max, blocks, method_name, True, examined_pairs,
        reconstruction_mode,
    )
    ok, message = verify_scheme(scheme)
    if not ok:
        raise AssertionError(message)
    return ShareTableOptimizationResult(
        scheme,
        type_tables,
        allocation_rows,
        selected_allocation_ids,
        raw_count,
        len(deduplicated) if deduplicated_count_override is None else deduplicated_count_override,
        len(allocation_rows),
        solver_name,
        threshold,
    )


def optimize_share_matrix_method(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
) -> ShareTableOptimizationResult:
    """Enumerate recovery matrices and canonical allocations, then minimize regions.

    Complete ``(k,n)`` thresholds use exactly k share types and the unique
    all-ones recovery row.  General structures enumerate valid affine recovery
    matrices for 1 through ``max_share_types`` types.
    """
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    n = len(people)
    index = {p: i for i, p in enumerate(people)}
    q_masks = tuple(_set_mask(q, index) for q in q_min)
    f_masks = tuple(_set_mask(f, index) for f in f_max)
    threshold = _threshold_parameters(q_masks, f_masks, n)
    if threshold:
        type_counts = [threshold[0]]
    else:
        type_counts = range(1, min(n, max_share_types or n) + 1)

    raw = []
    examined_pairs = 0
    for type_count in type_counts:
        if threshold:
            recovery_tables = [((1 << type_count) - 1,)]
        else:
            recovery_tables = list(enumerate_recovery_matrices(type_count))

        # Formulas depend only on the recovery matrix and are reused by allocations.
        prepared_tables = []
        for recovery_masks in recovery_tables:
            type_formulas, _, _ = _formulas_for_region(recovery_masks, tuple(range(type_count)))
            # Identical nominal type formulas belong to a smaller type-count case.
            formula_keys = {
                (formula.secret_coefficient, formula.random_terms)
                for formula in type_formulas.values()
            }
            if len(formula_keys) != type_count:
                continue
            prepared_tables.append((recovery_masks, type_formulas))

        for labels in _restricted_growth_surjections(n, type_count):
            for recovery_masks, type_formulas in prepared_tables:
                examined_pairs += 1
                if examined_pairs > max_candidate_pairs:
                    raise ValueError(
                        f"recovery-matrix/allocation pairs exceed {max_candidate_pairs}; "
                        "raise max_candidate_pairs to continue exact enumeration"
                    )
                if not _matrix_secure(recovery_masks, labels, f_masks):
                    continue
                recovery_set = frozenset(recovery_masks)
                coverage = _coverage_from_matrix(recovery_set, labels, q_masks)
                if not coverage:
                    continue
                formulas = {
                    participant: type_formulas[labels[i]]
                    for i, participant in enumerate(people)
                }
                table, assignment, checked_coverage, covered = _make_tables_for_formulas(
                    len(raw), formulas, q_min
                )
                if checked_coverage != coverage:
                    raise AssertionError("matrix coverage and formula coverage disagree")
                # Store every recovery row, not just rows used by current targets.
                # RGS order guarantees first type appearances are 0,1,...,t-1.
                all_recovery_combinations = tuple(
                    tuple(i for i in range(type_count) if mask & (1 << i))
                    for mask in recovery_masks
                )
                table = ShareTypeTable(
                    table.table_id,
                    table.types,
                    all_recovery_combinations,
                    True,
                )
                raw.append((table, assignment, formulas, coverage, covered, 0))

    return _finish_matrix_optimization(
        people, q_min, f_max, raw, examined_pairs, threshold, ilp_backend,
        "share-recovery-matrix-v2+ILP",
    )


def _assignment_profile(labels, qualified_masks, forbidden_masks):
    """Compute type signatures for all qualified/forbidden sets in one allocation."""
    qualified_signatures = []
    for qualified in qualified_masks:
        signature = 0
        for participant, label in enumerate(labels):
            if qualified & (1 << participant):
                signature ^= 1 << label
        qualified_signatures.append(signature)

    forbidden_observed_types = []
    for forbidden in forbidden_masks:
        observed = 0
        for participant, label in enumerate(labels):
            if forbidden & (1 << participant):
                observed |= 1 << label
        forbidden_observed_types.append(observed)
    return tuple(qualified_signatures), tuple(forbidden_observed_types)


@lru_cache(maxsize=32)
def _cached_assignment_profiles(n, type_count, qualified_masks, forbidden_masks):
    """Cache access-specific RGS allocations and coalition signatures."""
    return tuple(
        (labels, *_assignment_profile(labels, qualified_masks, forbidden_masks))
        for labels in _restricted_growth_surjections(n, type_count)
    )


def _stirling_second_kind_capped(n: int, k: int, cap: int) -> int:
    """Compute S(n,k), stopping above cap to avoid caching a large Bell enumeration."""
    row = [0] * (k + 1)
    row[0] = 1
    for size in range(1, n + 1):
        new = [0] * (k + 1)
        for groups in range(1, min(size, k) + 1):
            new[groups] = min(
                cap + 1,
                row[groups - 1] + groups * row[groups],
            )
        row = new
    return row[k]


def optimize_share_matrix_method_v21(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
    stop_at_one_region: bool = True,
    online_dominance: bool = False,
    cache_assignment_profiles: bool = False,
    _method_name: str = "share-recovery-matrix-v2.1+ILP",
) -> ShareTableOptimizationResult:
    """Preserve the exact objective and security rules while avoiding repeated work.

    Qualified signatures and forbidden visible types are computed once per
    allocation; recovery-matrix catalogs are cached by type count; cheap
    security and coverage checks precede RREF; formulas are cached by recovery
    matrix.  The search stops at the global lower bound
    of one region unless ``stop_at_one_region=False`` requests full enumeration.
    """
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    n = len(people)
    index = {p: i for i, p in enumerate(people)}
    q_masks = tuple(_set_mask(q, index) for q in q_min)
    f_masks = tuple(_set_mask(f, index) for f in f_max)
    threshold = _threshold_parameters(q_masks, f_masks, n)

    # One region is the global lower bound.  Return immediately when every
    # qualified target is safely compatible. Optimality is then already proved.
    if stop_at_one_region and region_compatible(q_masks, f_masks, n):
        formulas, _, _ = _formulas_for_region(q_masks, people)
        table, assignment, coverage, covered = _make_tables_for_formulas(0, formulas, q_min)
        labels = tuple(assignment[participant] for participant in people)
        recovery_rows = []
        for coalition in q_min:
            recovery = 0
            for participant in coalition:
                recovery ^= 1 << assignment[participant]
            recovery_rows.append(recovery)
        recovery_masks = frozenset(recovery_rows)
        full_coverage = (1 << len(q_min)) - 1
        if coverage == full_coverage:
            raw = [(table, assignment, formulas, coverage, covered, full_coverage)]
            return _finish_matrix_optimization(
                people, q_min, f_max, raw, 1, threshold, ilp_backend,
                f"{_method_name}-one-region-optimum",
            )

    # Threshold structures already use S(n,k) specialized enumeration and their
    # columns are non-dominating; avoid online-frontier bookkeeping on this path.
    if threshold:
        online_dominance = False
        cache_assignment_profiles = False

    if threshold:
        type_counts = [threshold[0]]
    else:
        type_counts = range(1, min(n, max_share_types or n) + 1)

    raw = []
    logical_raw_count = 0
    seen_coverages = set()
    frontier_by_coverage = {}
    examined_pairs = 0
    for type_count in type_counts:
        recovery_tables = (
            (((1 << type_count) - 1,),)
            if threshold
            else _cached_recovery_matrices(type_count)
        )

        should_cache_profiles = (
            cache_assignment_profiles
            and _stirling_second_kind_capped(n, type_count, 2_000) <= 2_000
        )
        if should_cache_profiles:
            assignment_profiles = _cached_assignment_profiles(
                n, type_count, q_masks, f_masks
            )
        else:
            assignment_profiles = (
                (labels, *_assignment_profile(labels, q_masks, f_masks))
                for labels in _restricted_growth_surjections(n, type_count)
            )

        for labels, q_signatures, f_observed in assignment_profiles:

            for recovery_masks in recovery_tables:
                examined_pairs += 1
                if examined_pairs > max_candidate_pairs:
                    raise ValueError(
                        f"recovery-matrix/allocation pairs exceed {max_candidate_pairs}; "
                        "raise max_candidate_pairs to continue exact enumeration"
                    )

                # A forbidden coalition is unsafe if it owns every type in a row.
                if any(
                    recovery & ~observed == 0
                    for observed in f_observed
                    for recovery in recovery_masks
                ):
                    continue

                recovery_set = frozenset(recovery_masks)
                coverage = 0
                for qid, signature in enumerate(q_signatures):
                    if signature not in recovery_set:
                        continue
                    coverage |= 1 << qid
                if not coverage:
                    continue

                # Delay expensive RREF until all cheap combinatorial checks pass.
                type_formulas = _cached_type_formulas(type_count, tuple(recovery_masks))
                if type_formulas is None:
                    continue
                logical_raw_count += 1
                seen_coverages.add(coverage)

                # A unit-cost column strictly dominated by known coverage cannot
                # improve the optimum.  Remove it before constructing full rows.
                if online_dominance and any(
                    coverage != kept and coverage | kept == kept
                    for kept in frontier_by_coverage
                ):
                    continue
                formulas = {
                    participant: type_formulas[labels[i]]
                    for i, participant in enumerate(people)
                }
                table, assignment, checked_coverage, covered = _make_tables_for_formulas(
                    len(raw), formulas, q_min
                )
                if checked_coverage != coverage:
                    raise AssertionError("matrix coverage and formula coverage disagree")
                all_recovery_combinations = tuple(
                    tuple(i for i in range(type_count) if mask & (1 << i))
                    for mask in recovery_masks
                )
                table = ShareTypeTable(
                    table.table_id,
                    table.types,
                    all_recovery_combinations,
                    True,
                )
                item = (table, assignment, formulas, coverage, covered, 0)
                if not online_dominance:
                    raw.append(item)
                    continue

                old = frontier_by_coverage.get(coverage)
                if old is None:
                    frontier_by_coverage[coverage] = item
                else:
                    old_table = old[0]
                    new_key = (
                        len(table.types),
                        sum(len(formula.random_terms) for formula in table.types),
                    )
                    old_key = (
                        len(old_table.types),
                        sum(len(formula.random_terms) for formula in old_table.types),
                    )
                    if new_key < old_key:
                        frontier_by_coverage[coverage] = item

                # New coverage strictly contains old coverage: remove the old row.
                for kept in tuple(frontier_by_coverage):
                    if kept != coverage and kept | coverage == coverage:
                        del frontier_by_coverage[kept]

    if online_dominance:
        raw = list(frontier_by_coverage.values())

    return _finish_matrix_optimization(
        people, q_min, f_max, raw, examined_pairs, threshold, ilp_backend,
        _method_name,
        raw_count_override=logical_raw_count if online_dominance else None,
        deduplicated_count_override=len(seen_coverages) if online_dominance else None,
    )


def _optimize_threshold_allocations(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
    stop_at_one_region: bool = True,
) -> ShareTableOptimizationResult:
    """Internal allocation path used when a complete threshold input is detected."""
    return optimize_share_matrix_method_v21(
        qualified,
        forbidden,
        participants=participants,
        max_share_types=max_share_types,
        max_candidate_pairs=max_candidate_pairs,
        ilp_backend=ilp_backend,
        stop_at_one_region=stop_at_one_region,
        online_dominance=True,
        cache_assignment_profiles=True,
        _method_name="threshold-share-allocation-frontier+ILP",
    )


def _optimize_sgsr_impl(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
    stop_at_one_region: bool = True,
    reconstruction_mode: str = "standard",
) -> ShareTableOptimizationResult:
    """Enumerate only minimal recovery closures induced by qualified signatures.

    For each RGS allocation, compute qualified XOR type signatures first and
    generate their minimal affine closures instead of scanning all affine
    matrices.  Extra recovery rows add no qualified coverage and only increase
    forbidden leakage risk, so removing them preserves the optimal coverage
    family.  Threshold inputs still use the dedicated threshold path.
    """
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    reconstruction_mode = reconstruction_mode.lower()
    if reconstruction_mode not in {"standard", "mi", "mifr"}:
        raise ValueError("reconstruction_mode must be standard, mi, or mifr")
    n = len(people)
    index = {participant: i for i, participant in enumerate(people)}
    minimal_q_masks = tuple(_set_mask(q, index) for q in q_min)
    f_masks = tuple(_set_mask(f, index) for f in f_max)
    threshold = _threshold_parameters(minimal_q_masks, f_masks, n)
    if threshold and reconstruction_mode == "standard":
        return _optimize_threshold_allocations(
            q_min,
            f_max,
            participants=people,
            max_share_types=max_share_types,
            max_candidate_pairs=max_candidate_pairs,
            ilp_backend=ilp_backend,
            stop_at_one_region=stop_at_one_region,
        )

    if reconstruction_mode == "standard":
        q_targets = q_min
    else:
        target_masks = [
            mask for mask in range(1, 1 << n)
            if any(base & mask == base for base in minimal_q_masks)
        ]
        q_targets = tuple(
            frozenset(people[i] for i in range(n) if mask & (1 << i))
            for mask in target_masks
        )
    q_masks = tuple(_set_mask(q, index) for q in q_targets)

    if stop_at_one_region and region_compatible(q_masks, f_masks, n):
        formulas, _, _ = _formulas_for_region(q_masks, people)
        table, assignment, coverage, covered = _make_tables_for_formulas(0, formulas, q_targets)
        labels = tuple(assignment[participant] for participant in people)
        recovery_rows = []
        for coalition in q_targets:
            recovery = 0
            for participant in coalition:
                recovery ^= 1 << assignment[participant]
            recovery_rows.append(recovery)
        full_coverage = (1 << len(q_targets)) - 1
        if coverage == full_coverage:
            return _finish_matrix_optimization(
                people,
                q_targets,
                f_max,
                [(table, assignment, formulas, coverage, covered, full_coverage)],
                1,
                None,
                ilp_backend,
                f"sgsr-{reconstruction_mode}-one-region-optimum",
                reconstruction_mode=reconstruction_mode,
                require_full_recovery=reconstruction_mode == "mifr",
            )

    type_counts = range(1, min(n, max_share_types or n) + 1)
    frontier_by_coverage = {}
    seen_coverages = set()
    logical_raw_count = 0
    examined_pairs = 0

    for type_count in type_counts:
        assignment_profiles = _cached_assignment_profiles(
            n, type_count, q_masks, f_masks
        ) if _stirling_second_kind_capped(n, type_count, 2_000) <= 2_000 else (
            (labels, *_assignment_profile(labels, q_masks, f_masks))
            for labels in _restricted_growth_surjections(n, type_count)
        )

        for labels, q_signatures, f_observed in assignment_profiles:
            recovery_tables = _safe_qualified_induced_recovery_matrices(
                tuple(sorted(set(q_signatures))),
                tuple(sorted(set(f_observed))),
            )
            for recovery_masks in recovery_tables:
                examined_pairs += 1
                if examined_pairs > max_candidate_pairs:
                    raise ValueError(
                        f"induced-closure/allocation pairs exceed {max_candidate_pairs}; "
                        "raise max_candidate_pairs to continue exact enumeration"
                    )
                recovery_set = frozenset(recovery_masks)
                coverage = 0
                for qid, signature in enumerate(q_signatures):
                    if signature not in recovery_set:
                        continue
                    coverage |= 1 << qid
                if not coverage:
                    continue

                type_formulas = _cached_type_formulas(type_count, tuple(recovery_masks))
                if type_formulas is None:
                    continue
                logical_raw_count += 1
                seen_coverages.add(coverage)
                if any(
                    coverage != kept and coverage | kept == kept
                    for kept in frontier_by_coverage
                ):
                    continue

                formulas = {
                    participant: type_formulas[labels[i]]
                    for i, participant in enumerate(people)
                }
                table, assignment, checked_coverage, covered = _make_tables_for_formulas(
                    logical_raw_count - 1, formulas, q_targets
                )
                if checked_coverage != coverage:
                    raise AssertionError("induced-closure coverage and formula coverage disagree")
                table = ShareTypeTable(
                    table.table_id,
                    table.types,
                    tuple(
                        tuple(i for i in range(type_count) if mask & (1 << i))
                        for mask in recovery_masks
                    ),
                    True,
                )
                item = (table, assignment, formulas, coverage, covered, 0)
                old = frontier_by_coverage.get(coverage)
                if old is None:
                    frontier_by_coverage[coverage] = item
                else:
                    old_table = old[0]
                    new_key = (
                        len(table.types),
                        sum(len(formula.random_terms) for formula in table.types),
                    )
                    old_key = (
                        len(old_table.types),
                        sum(len(formula.random_terms) for formula in old_table.types),
                    )
                    if new_key < old_key:
                        frontier_by_coverage[coverage] = item
                for kept in tuple(frontier_by_coverage):
                    if kept != coverage and kept | coverage == coverage:
                        del frontier_by_coverage[kept]

    return _finish_matrix_optimization(
        people,
        q_targets,
        f_max,
        list(frontier_by_coverage.values()),
        examined_pairs,
        None,
        ilp_backend,
        f"sgsr-{reconstruction_mode}-qualified-induced+ILP",
        raw_count_override=logical_raw_count,
        deduplicated_count_override=len(seen_coverages),
        reconstruction_mode=reconstruction_mode,
        require_full_recovery=reconstruction_mode == "mifr",
    )


def optimize_sgsr(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
    stop_at_one_region: bool = True,
    reconstruction_mode: str = "standard",
) -> ShareTableOptimizationResult:
    """Run the final Share Allocation and Recovery Relations algorithm.

    This is the stable public name of the qualified-signature-induced
    implementation.  The legacy implementation name is kept internally only
    to preserve equivalence with the development test suite.
    """
    return _optimize_sgsr_impl(
        qualified,
        forbidden,
        participants=participants,
        max_share_types=max_share_types,
        max_candidate_pairs=max_candidate_pairs,
        ilp_backend=ilp_backend,
        stop_at_one_region=stop_at_one_region,
        reconstruction_mode=reconstruction_mode,
    )


def compare_two_methods(
    qualified,
    forbidden,
    *,
    participants=None,
    max_general_subsets=1_000_000,
    max_share_types=None,
    max_candidate_pairs=2_000_000,
    ilp_backend="auto",
) -> ComparisonResult:
    """Run the paper subset method and recovery-matrix method with comparable metrics."""
    started = perf_counter()
    paper = optimize_share_tables(
        qualified,
        forbidden,
        participants=participants,
        max_general_subsets=max_general_subsets,
        ilp_backend=ilp_backend,
        use_threshold_specialization=False,
    )
    paper_seconds = perf_counter() - started
    started = perf_counter()
    matrix = optimize_share_matrix_method(
        qualified,
        forbidden,
        participants=participants,
        max_share_types=max_share_types,
        max_candidate_pairs=max_candidate_pairs,
        ilp_backend=ilp_backend,
    )
    matrix_seconds = perf_counter() - started

    def summary(name, result, elapsed):
        return MethodComparison(
            name,
            result.scheme.pixel_expansion,
            result.raw_candidate_count,
            result.deduplicated_candidate_count,
            result.nondominated_candidate_count,
            elapsed,
            result.solver,
        )
    return ComparisonResult(
        summary("paper qualified-subset enumeration", paper, paper_seconds),
        summary("share recovery-matrix method", matrix, matrix_seconds),
        paper,
        matrix,
    )


def format_comparison(comparison: ComparisonResult) -> str:
    """Render a compact English comparison table for two methods."""
    rows = [comparison.paper_method, comparison.matrix_method]
    lines = [
        (
            "Method | Optimal regions | Raw candidates | Deduplicated | "
            "Nondominated | Seconds | Solver"
        ),
        "-" * 100,
    ]
    for row in rows:
        lines.append(
            f"{row.method} | {row.optimal_regions} | {row.raw_candidates} | "
            f"{row.deduplicated_candidates} | {row.nondominated_candidates} | "
            f"{row.elapsed_seconds:.6f} | {row.solver}"
        )
    return "\n".join(lines)


def compare_three_methods(
    qualified,
    forbidden,
    *,
    participants=None,
    max_general_subsets=1_000_000,
    max_share_types=None,
    max_candidate_pairs=2_000_000,
    ilp_backend="auto",
) -> ThreeMethodComparisonResult:
    """Compare the paper method and two exact matrix implementations in one call."""
    calls = (
        (
            "paper qualified-subset enumeration",
            lambda: optimize_share_tables(
                qualified,
                forbidden,
                participants=participants,
                max_general_subsets=max_general_subsets,
                ilp_backend=ilp_backend,
                use_threshold_specialization=False,
            ),
        ),
        (
            "V2 share recovery-matrix method",
            lambda: optimize_share_matrix_method(
                qualified,
                forbidden,
                participants=participants,
                max_share_types=max_share_types,
                max_candidate_pairs=max_candidate_pairs,
                ilp_backend=ilp_backend,
            ),
        ),
        (
            "V2.1 deferred elimination and caching",
            lambda: optimize_share_matrix_method_v21(
                qualified,
                forbidden,
                participants=participants,
                max_share_types=max_share_types,
                max_candidate_pairs=max_candidate_pairs,
                ilp_backend=ilp_backend,
            ),
        ),
    )
    summaries = []
    results = []
    for name, call in calls:
        started = perf_counter()
        result = call()
        elapsed = perf_counter() - started
        summaries.append(
            MethodComparison(
                name,
                result.scheme.pixel_expansion,
                result.raw_candidate_count,
                result.deduplicated_candidate_count,
                result.nondominated_candidate_count,
                elapsed,
                result.solver,
            )
        )
        results.append(result)
    return ThreeMethodComparisonResult(*summaries, *results)


def format_three_method_comparison(comparison: ThreeMethodComparisonResult) -> str:
    """Render the three-method comparison using the standard columns."""
    rows = [comparison.paper_method, comparison.v2_method, comparison.v21_method]
    lines = [
        (
            "Method | Optimal regions | Raw candidates | Deduplicated | "
            "Nondominated | Seconds | Solver"
        ),
        "-" * 100,
    ]
    for row in rows:
        lines.append(
            f"{row.method} | {row.optimal_regions} | {row.raw_candidates} | "
            f"{row.deduplicated_candidates} | {row.nondominated_candidates} | "
            f"{row.elapsed_seconds:.6f} | {row.solver}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    result = compare_two_methods(
        [{1, 2}, {1, 3, 4}],
        [{1, 3}, {1, 4}, {2, 3, 4}],
        participants=range(1, 5),
        ilp_backend="branch-and-bound",
    )
    print(format_comparison(result))

"""Bitset-pruned implementation of Shen's qualified-subset method.

Compatible qualified groups form a downward-closed family.  The search starts
from the full group: compatible nodes become maximal candidates immediately;
incompatible nodes are reduced to a minimal conflict witness C and branch only
to ``G - {q}`` for ``q in C``.  Python integer bitsets support ``g > 64``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
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
    ShareTableOptimizationResult,
    _deduplicate_and_remove_dominated,
    _make_tables_for_formulas,
    _solve_ilp,
)


@dataclass(frozen=True)
class MaximalCompatibleEnumeration:
    """Maximal-compatible-group results and reproducible statistics."""

    maximal_group_masks: tuple[int, ...]
    compatibility_checks: int
    visited_nodes: int
    conflict_count: int
    inferred_conflict_nodes: int
    witness_shrink_checks: int
    elapsed_seconds: float


@dataclass
class PrunedPaperResult:
    optimization: ShareTableOptimizationResult
    enumeration: MaximalCompatibleEnumeration


class EnumerationLimitExceeded(RuntimeError):
    """An explicit resource limit was reached; attached statistics are partial."""

    def __init__(self, message, *, compatibility_checks, visited_nodes, conflict_count, elapsed_seconds):
        super().__init__(message)
        self.compatibility_checks = compatibility_checks
        self.visited_nodes = visited_nodes
        self.conflict_count = conflict_count
        self.elapsed_seconds = elapsed_seconds


def _iter_set_bits(mask: int):
    """Yield set-bit positions from low to high without a length-g Boolean list."""
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def enumerate_maximal_compatible_groups(
    qualified_masks,
    forbidden_masks,
    participant_count: int,
    *,
    max_compatibility_checks: int = 5_000_000,
    max_visited_nodes: int | None = None,
) -> MaximalCompatibleEnumeration:
    """Enumerate maximal compatible qualified groups with conflict branching.

    Bit i in each returned integer indicates inclusion of minimal qualified
    coalition i.  Resource limits raise an exception rather than returning an
    incomplete result as if it were exact.
    """
    qualified_masks = tuple(qualified_masks)
    forbidden_masks = tuple(forbidden_masks)
    if not qualified_masks:
        raise ValueError("at least one qualified coalition is required")
    if max_compatibility_checks < 1:
        raise ValueError("max_compatibility_checks must be positive")
    if max_visited_nodes is not None and max_visited_nodes < 1:
        raise ValueError("max_visited_nodes must be positive or None")

    started = perf_counter()
    cache = {}
    check_count = 0
    shrink_checks = 0
    conflict_count = 0
    inferred_conflict_nodes = 0
    visited = set()
    maximal = set()
    # Known minimal conflicts form a hypergraph. C subset G proves G incompatible.
    conflict_witnesses = set()

    def compatible(group_mask: int) -> bool:
        nonlocal check_count
        old = cache.get(group_mask)
        if old is not None:
            return old
        check_count += 1
        if check_count > max_compatibility_checks:
            raise EnumerationLimitExceeded(
                f"compatibility checks exceeded {max_compatibility_checks}",
                compatibility_checks=check_count - 1,
                visited_nodes=len(visited),
                conflict_count=conflict_count,
                elapsed_seconds=perf_counter() - started,
            )
        region = [
            qualified_masks[index]
            for index in _iter_set_bits(group_mask)
        ]
        value = region_compatible(region, forbidden_masks, participant_count)
        cache[group_mask] = value
        return value

    def minimal_conflict(group_mask: int) -> int:
        """Delete elements while preserving conflict to obtain a minimal witness."""
        nonlocal shrink_checks
        witness = group_mask
        # One pass suffices: if deletion becomes compatible, every subset is too.
        for index in tuple(_iter_set_bits(group_mask)):
            trial = witness & ~(1 << index)
            if not trial:
                continue
            shrink_checks += 1
            if not compatible(trial):
                witness = trial
        return witness

    def add_maximal(group_mask: int):
        # Different conflict branches may reach a group dominated by a known one.
        if any(group_mask | kept == kept for kept in maximal):
            return
        for kept in tuple(maximal):
            if kept | group_mask == group_mask:
                maximal.remove(kept)
        maximal.add(group_mask)

    def search(group_mask: int):
        nonlocal conflict_count, inferred_conflict_nodes
        if not group_mask or group_mask in visited:
            return
        if max_visited_nodes is not None and len(visited) >= max_visited_nodes:
            raise EnumerationLimitExceeded(
                f"maximal-compatible-group search exceeded {max_visited_nodes} nodes",
                compatibility_checks=check_count,
                visited_nodes=len(visited),
                conflict_count=conflict_count,
                elapsed_seconds=perf_counter() - started,
            )
        visited.add(group_mask)

        witness = next(
            (known for known in conflict_witnesses if known & group_mask == known),
            None,
        )
        if witness is None:
            if compatible(group_mask):
                add_maximal(group_mask)
                return
            witness = minimal_conflict(group_mask)
            # Keep only inclusion-minimal conflicts to accelerate later queries.
            if not any(known & witness == known for known in conflict_witnesses):
                conflict_witnesses.difference_update(
                    known for known in tuple(conflict_witnesses)
                    if known & witness == witness
                )
                conflict_witnesses.add(witness)
        else:
            inferred_conflict_nodes += 1

        conflict_count += 1
        # Every compatible subset omits a witness element; branch on that condition.
        for index in _iter_set_bits(witness):
            search(group_mask & ~(1 << index))

    search((1 << len(qualified_masks)) - 1)
    ordered = tuple(sorted(maximal, key=lambda mask: (-mask.bit_count(), mask)))
    return MaximalCompatibleEnumeration(
        ordered,
        check_count,
        len(visited),
        conflict_count,
        inferred_conflict_nodes,
        shrink_checks,
        perf_counter() - started,
    )


def optimize_pruned_paper_method(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_compatibility_checks: int = 5_000_000,
    max_visited_nodes: int | None = None,
    ilp_backend: str = "auto",
) -> PrunedPaperResult:
    """Enumerate maximal groups, build both share tables, and minimize regions."""
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    index = {participant: i for i, participant in enumerate(people)}
    q_masks = tuple(_set_mask(group, index) for group in q_min)
    f_masks = tuple(_set_mask(group, index) for group in f_max)

    enumeration = enumerate_maximal_compatible_groups(
        q_masks,
        f_masks,
        len(people),
        max_compatibility_checks=max_compatibility_checks,
        max_visited_nodes=max_visited_nodes,
    )

    raw = []
    for source_mask in enumeration.maximal_group_masks:
        source_ids = tuple(_iter_set_bits(source_mask))
        region_masks = [q_masks[index] for index in source_ids]
        formulas, _, _ = _formulas_for_region(region_masks, people)
        table, assignment, coverage, covered = _make_tables_for_formulas(
            len(raw), formulas, q_min
        )
        raw.append((table, assignment, formulas, coverage, covered, source_mask))

    deduplicated, type_tables, allocation_rows = _deduplicate_and_remove_dominated(raw, q_min)
    selected_indices, solver = _solve_ilp(allocation_rows, len(q_min), ilp_backend)
    blocks = []
    for block_id, row_index in enumerate(selected_indices, 1):
        row = allocation_rows[row_index]
        random_terms = {
            term
            for formula in row.formulas.values()
            for term in formula.random_terms
        }
        blocks.append(AllocationBlock(
            block_id,
            row.covered_qualified,
            row.formulas,
            len(people) - len(random_terms),
            len(random_terms),
        ))
    scheme = ShareReuseScheme(
        people,
        q_min,
        f_max,
        blocks,
        "paper-maximal-compatible-bitmask-pruning+ILP",
        True,
        enumeration.compatibility_checks,
    )
    ok, message = verify_scheme(scheme)
    if not ok:
        raise AssertionError(message)

    result = ShareTableOptimizationResult(
        scheme,
        type_tables,
        allocation_rows,
        [allocation_rows[index].allocation_id for index in selected_indices],
        len(raw),
        len(deduplicated),
        len(allocation_rows),
        solver,
        None,
    )
    return PrunedPaperResult(result, enumeration)


if __name__ == "__main__":
    answer = optimize_pruned_paper_method(
        [{1, 2}, {2, 3}, {3, 4}],
        [{1, 3}, {1, 4}, {2, 4}],
        participants=range(1, 5),
        ilp_backend="branch-and-bound",
    )
    print("maximal-group bitsets:", answer.enumeration.maximal_group_masks)
    print("compatibility checks:", answer.enumeration.compatibility_checks)
    print("optimal regions:", answer.optimization.scheme.pixel_expansion)

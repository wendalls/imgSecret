"""Share-reusing XOR visual secret sharing for general access structures.

Each pixel region represents a GF(2) equation ``XOR_{i in Q_j} x_i = S``.
The same random variable may be reused across recovery equations, so qualified
coalitions may overlap and may have different cardinalities.

The implementation keeps a recoverable-share formula table.  Every region
records its recovery groups, participant formulas, equation rank, and number
of free random variables.  Polynomial GF(2) consistency and rank tests replace
the explicit ``2^g`` parity-combination check in Lemma 4.
"""

from __future__ import annotations

import random
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass

Participant = Hashable
ParticipantSet = frozenset[Participant]


@dataclass(frozen=True)
class LinearShareFormula:
    """A share formula: ``secret_coefficient*S XOR random_terms``."""
    secret_coefficient: int
    random_terms: tuple[Participant, ...]

    def __str__(self) -> str:
        terms = (["S"] if self.secret_coefficient else []) + [f"R[{p}]" for p in self.random_terms]
        return " XOR ".join(terms) if terms else "0"


@dataclass(frozen=True)
class AllocationBlock:
    """One recovery-table row and one pixel region of the final shares."""
    block_id: int
    recovered_qualified: tuple[ParticipantSet, ...]
    share_formulas: Mapping[Participant, LinearShareFormula]
    rank: int
    random_variable_count: int


@dataclass
class ShareReuseScheme:
    participants: tuple[Participant, ...]
    minimal_qualified: tuple[ParticipantSet, ...]
    maximal_forbidden: tuple[ParticipantSet, ...]
    blocks: list[AllocationBlock]
    method: str
    optimal: bool
    compatibility_checks: int
    # standard permits a recovering subset; MI/MIFR require direct full-coalition XOR.
    reconstruction_mode: str = "standard"

    @property
    def pixel_expansion(self) -> int:
        return len(self.blocks)


def _stable_key(value: Participant) -> tuple[str, str]:
    return type(value).__name__, repr(value)


def _set_sort_key(s: ParticipantSet):
    return len(s), tuple(_stable_key(x) for x in sorted(s, key=_stable_key))


def _minimal_sets(sets: Iterable[Iterable[Participant]]) -> tuple[ParticipantSet, ...]:
    unique = {frozenset(s) for s in sets}
    if frozenset() in unique:
        raise ValueError("qualified coalitions cannot contain the empty set")
    return tuple(sorted((s for s in unique if not any(t < s for t in unique)), key=_set_sort_key))


def _maximal_sets(sets: Iterable[Iterable[Participant]]) -> tuple[ParticipantSet, ...]:
    unique = {frozenset(s) for s in sets}
    return tuple(sorted((s for s in unique if not any(s < t for t in unique)), key=_set_sort_key))


def normalise_access_structure(qualified, forbidden, participants=None):
    """Keep minimal qualified and maximal forbidden sets and reject conflicts."""
    q_min = _minimal_sets(qualified)
    f_max = _maximal_sets(forbidden)
    if not q_min:
        raise ValueError("at least one qualified coalition is required")
    universe = set(participants or ())
    for s in (*q_min, *f_max):
        universe.update(s)
    for q in q_min:
        for f in f_max:
            if q <= f:
                raise ValueError(
                    f"access-structure conflict: forbidden coalition {set(f)!r} "
                    f"contains qualified coalition {set(q)!r}"
                )
    return tuple(sorted(universe, key=_stable_key)), q_min, f_max


def _set_mask(s, index):
    mask = 0
    for p in s:
        mask |= 1 << index[p]
    return mask


# GF(2) vectors are Python integer bitsets; XOR is vector addition.
def _gf2_rank(vectors: Iterable[int]) -> int:
    basis = {}
    for value in vectors:
        x = value
        while x:
            pivot = x.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = x
                break
            x ^= basis[pivot]
    return len(basis)


def _gf2_consistent(equations: Sequence[int], rhs: Sequence[int]) -> bool:
    """Check consistency of GF(2) equations stored as integer bitsets."""
    basis = {}
    for coefficients, value in zip(equations, rhs):
        a, b = coefficients, value & 1
        while a:
            pivot = a.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = (a, b)
                break
            old_a, old_b = basis[pivot]
            a ^= old_a
            b ^= old_b
        if not a and b:
            return False
    return True


def _in_span(target: int, vectors: Iterable[int]) -> bool:
    basis = {}
    for value in vectors:
        x = value
        while x:
            pivot = x.bit_length() - 1
            if pivot not in basis:
                basis[pivot] = x
                break
            x ^= basis[pivot]
    x = target
    while x:
        pivot = x.bit_length() - 1
        if pivot not in basis:
            return False
        x ^= basis[pivot]
    return True


def _rref(row_masks: Sequence[int], rhs: Sequence[int], n: int):
    """Compute reduced row-echelon form for the participant system Ax=rhs."""
    rows = [[a, b & 1] for a, b in zip(row_masks, rhs)]
    rank, pivots = 0, []
    for column in range(n):
        pivot_row = next((r for r in range(rank, len(rows)) if rows[r][0] & (1 << column)), None)
        if pivot_row is None:
            continue
        rows[rank], rows[pivot_row] = rows[pivot_row], rows[rank]
        for r in range(len(rows)):
            if r != rank and rows[r][0] & (1 << column):
                rows[r][0] ^= rows[rank][0]
                rows[r][1] ^= rows[rank][1]
        pivots.append(column)
        rank += 1
    if any(mask == 0 and value for mask, value in rows):
        raise ValueError("qualified recovery equations Ax=S are inconsistent")
    return rows[:rank], pivots


def region_compatible(region_masks: Sequence[int], forbidden_masks: Sequence[int], n: int) -> bool:
    """Check whether qualified coalitions can share one region in polynomial time.

    No odd XOR of recovery equations may fall inside a forbidden coalition,
    and no nonempty even XOR may be a subset of a minimal qualified coalition
    assigned to this region.
    """
    g = len(region_masks)
    if g <= 1:
        return True
    odd_constraint = (1 << g) - 1
    columns = []
    for p in range(n):
        column = 0
        for j, qmask in enumerate(region_masks):
            if qmask & (1 << p):
                column |= 1 << j
        columns.append(column)

    universe = (1 << n) - 1
    for forbidden in forbidden_masks:
        outside = universe & ~forbidden
        equations = [columns[p] for p in range(n) if outside & (1 << p)] + [odd_constraint]
        if _gf2_consistent(equations, [0] * (len(equations) - 1) + [1]):
            return False

    full_rank = _gf2_rank([*columns, odd_constraint])
    for qmask in region_masks:
        outside_columns = [columns[p] for p in range(n) if not qmask & (1 << p)]
        if _gf2_rank([*outside_columns, odd_constraint]) < full_rank:
            return False
    return True


def _exact_cover(candidate_masks: Sequence[int], target: int) -> list[int]:
    """Find an exact minimum region cover using greedy bounds and memoization."""
    remaining, incumbent = target, []
    while remaining:
        best = max(range(len(candidate_masks)), key=lambda i: (candidate_masks[i] & remaining).bit_count())
        incumbent.append(best)
        remaining &= ~candidate_masks[best]
    best_solution = incumbent
    by_item = [[] for _ in range(target.bit_length())]
    for i, mask in enumerate(candidate_masks):
        for q in range(target.bit_length()):
            if mask & (1 << q):
                by_item[q].append(i)
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
        max_gain = max((mask & uncovered).bit_count() for mask in candidate_masks)
        lower = (uncovered.bit_count() + max_gain - 1) // max_gain
        if len(chosen) + lower >= len(best_solution):
            return
        items = [q for q in range(uncovered.bit_length()) if uncovered & (1 << q)]
        qid = min(items, key=lambda q: len(by_item[q]))
        options = sorted(by_item[qid], key=lambda i: (candidate_masks[i] & uncovered).bit_count(), reverse=True)
        for i in options:
            gain = candidate_masks[i] & uncovered
            if gain:
                dfs(uncovered & ~gain, chosen + [i])
    dfs(target, [])
    return best_solution


def _heuristic_partition(q_masks, restarts, seed, compatible):
    """Run randomized greedy grouping repeatedly and merge compatible regions."""
    rng = random.Random(seed)
    base = list(range(len(q_masks)))
    best_groups = [1 << i for i in base]
    for attempt in range(max(1, restarts)):
        order = base.copy()
        if attempt:
            rng.shuffle(order)
        else:
            order.sort(key=lambda i: (-q_masks[i].bit_count(), q_masks[i]))
        groups = []
        for qid in order:
            choices = []
            for pos, group in enumerate(groups):
                merged = group | (1 << qid)
                if compatible(merged):
                    choices.append((merged.bit_count(), pos, merged))
            if choices:
                _, pos, merged = max(choices)
                groups[pos] = merged
            else:
                groups.append(1 << qid)
        changed = True
        while changed:
            changed = False
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    merged = groups[i] | groups[j]
                    if compatible(merged):
                        groups[i], changed = merged, True
                        groups.pop(j)
                        break
                if changed:
                    break
        if len(groups) < len(best_groups):
            best_groups = groups
    return best_groups


def _formulas_for_region(region_masks, participants):
    """Express the solution of Ax=S as secret/random formulas per participant."""
    n = len(participants)
    rows, pivots = _rref(region_masks, [1] * len(region_masks), n)
    free = [i for i in range(n) if i not in set(pivots)]
    formulas = {
        participants[column]: LinearShareFormula(0, (participants[column],))
        for column in free
    }
    for (mask, rhs), pivot in zip(rows, pivots):
        terms = tuple(participants[column] for column in free if mask & (1 << column))
        formulas[participants[pivot]] = LinearShareFormula(rhs, terms)
    return formulas, len(pivots), len(free)


def build_share_reuse_scheme(
    qualified,
    forbidden,
    *,
    participants=None,
    mode="auto",
    exact_group_limit=16,
    heuristic_restarts=64,
    random_seed=0,
):
    """Build a share-reuse scheme for qualified coalitions of varying sizes."""
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    n = len(people)
    index = {p: i for i, p in enumerate(people)}
    q_masks = tuple(_set_mask(q, index) for q in q_min)
    f_masks = tuple(_set_mask(f, index) for f in f_max)
    q_count = len(q_masks)
    if mode not in {"auto", "exact", "heuristic"}:
        raise ValueError("mode must be 'auto', 'exact', or 'heuristic'")
    use_exact = mode == "exact" or (mode == "auto" and q_count <= exact_group_limit)
    if mode == "exact" and q_count > exact_group_limit:
        raise ValueError(
            f"exact mode must enumerate 2^{q_count}-1 subsets; "
            "raise the limit or use heuristic mode"
        )

    cache, compatibility_checks = {}, 0
    def compatible(group_mask):
        nonlocal compatibility_checks
        if group_mask not in cache:
            compatibility_checks += 1
            region = [q_masks[i] for i in range(q_count) if group_mask & (1 << i)]
            cache[group_mask] = region_compatible(region, f_masks, n)
        return cache[group_mask]

    if use_exact:
        candidates = [mask for mask in range(1, 1 << q_count) if compatible(mask)]
        candidates.sort(key=int.bit_count, reverse=True)
        maximal = []
        for candidate in candidates:
            if not any(candidate | kept == kept for kept in maximal):
                maximal.append(candidate)
        selected = [maximal[i] for i in _exact_cover(maximal, (1 << q_count) - 1)]
        method = "exact"
    else:
        selected = _heuristic_partition(q_masks, heuristic_restarts, random_seed, compatible)
        method = "heuristic"

    # Exact set-cover groups may overlap; deduplicated groups remain compatible.
    assigned, disjoint = 0, []
    for group in selected:
        group &= ~assigned
        if group:
            disjoint.append(group)
            assigned |= group

    blocks = []
    for block_id, group in enumerate(disjoint, 1):
        ids = [i for i in range(q_count) if group & (1 << i)]
        formulas, rank, random_count = _formulas_for_region([q_masks[i] for i in ids], people)
        blocks.append(AllocationBlock(block_id, tuple(q_min[i] for i in ids), formulas, rank, random_count))
    scheme = ShareReuseScheme(people, q_min, f_max, blocks, method, use_exact, compatibility_checks)
    ok, message = verify_scheme(scheme)
    if not ok:
        raise AssertionError(message)
    return scheme


def verify_scheme(scheme: ShareReuseScheme) -> tuple[bool, str]:
    """Verify qualified recovery and forbidden information-theoretic security."""
    recovered = set()
    for block in scheme.blocks:
        for q in block.recovered_qualified:
            secret, random_parity = 0, set()
            for p in q:
                formula = block.share_formulas[p]
                secret ^= formula.secret_coefficient
                for term in formula.random_terms:
                    random_parity.symmetric_difference_update({term})
            if secret != 1 or random_parity:
                return False, f"block {block.block_id} cannot recover {set(q)!r}"
            recovered.add(q)

        # A forbidden view is a*S+B*R; it is secure iff a lies in col(B).
        for f in scheme.maximal_forbidden:
            members = sorted(f, key=_stable_key)
            secret_vector, random_columns = 0, {}
            for row, p in enumerate(members):
                formula = block.share_formulas[p]
                if formula.secret_coefficient:
                    secret_vector |= 1 << row
                for term in formula.random_terms:
                    random_columns[term] = random_columns.get(term, 0) | (1 << row)
            if not _in_span(secret_vector, random_columns.values()):
                return False, f"block {block.block_id} leaks to forbidden {set(f)!r}"
    missing = set(scheme.minimal_qualified) - recovered
    return (False, f"uncovered: {missing!r}") if missing else (True, "ok")


def generate_binary_shares(secret, scheme: ShareReuseScheme, *, rng=None):
    """Generate binary scalar or NumPy image shares from the formula table."""
    import numpy as np
    secret_array = np.asarray(secret, dtype=np.uint8) & 1
    generator = rng if rng is not None else np.random.default_rng()
    output = {p: [] for p in scheme.participants}
    for block in scheme.blocks:
        free_terms = {term for formula in block.share_formulas.values() for term in formula.random_terms}
        random_values = {
            term: generator.integers(0, 2, size=secret_array.shape, dtype=np.uint8)
            for term in free_terms
        }
        for p in scheme.participants:
            formula = block.share_formulas[p]
            value = secret_array.copy() if formula.secret_coefficient else np.zeros_like(secret_array)
            for term in formula.random_terms:
                value ^= random_values[term]
            output[p].append(value)
    return {p: np.stack(parts, axis=-1) for p, parts in output.items()}


def reconstruct(shares: Mapping[Participant, object], coalition: Iterable[Participant]):
    """XOR participant shares; recovering regions equal the secret on the last axis."""
    import numpy as np
    members = list(coalition)
    if not members:
        raise ValueError("the reconstruction coalition cannot be empty")
    result = np.asarray(shares[members[0]]).copy()
    for p in members[1:]:
        result ^= np.asarray(shares[p])
    return result


def format_allocation_table(scheme: ShareReuseScheme) -> str:
    """Render the recoverable-share formula table as text."""
    lines = [
        (
            f"method={scheme.method}, proven optimal={scheme.optimal}, "
            f"pixel expansion={scheme.pixel_expansion}"
        ),
        f"compatibility checks={scheme.compatibility_checks}",
    ]
    for block in scheme.blocks:
        recovered = ", ".join("{" + ",".join(map(str, sorted(q, key=_stable_key))) + "}" for q in block.recovered_qualified)
        lines.append(
            f"\nregion {block.block_id}: recovers {recovered}; rank={block.rank}; "
            f"random variables={block.random_variable_count}"
        )
        for p in scheme.participants:
            lines.append(f"  P[{p}] = {block.share_formulas[p]}")
    return "\n".join(lines)


if __name__ == "__main__":
    result = build_share_reuse_scheme(
        [{1, 2}, {1, 3, 4}], [{1, 3}, {1, 4}, {2, 3, 4}], participants=range(1, 5)
    )
    print(format_allocation_table(result))

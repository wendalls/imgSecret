"""Access-structure utilities."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from itertools import combinations


def maximal_forbidden(
    participants: Iterable[Hashable],
    minimal_qualified: Iterable[Iterable[Hashable]],
) -> tuple[frozenset[Hashable], ...]:
    """Derive maximal forbidden sets from minimal qualified sets."""
    people = tuple(participants)
    qualified = tuple(frozenset(group) for group in minimal_qualified)
    forbidden = [
        frozenset(group)
        for size in range(len(people) + 1)
        for group in combinations(people, size)
        if not any(q <= frozenset(group) for q in qualified)
    ]
    return tuple(
        group for group in forbidden
        if not any(group < other for other in forbidden)
    )


def threshold_access_structure(k: int, n: int):
    """Return participants, minimal qualified and maximal forbidden sets."""
    if not 1 <= k <= n:
        raise ValueError("require 1 <= k <= n")
    people = tuple(range(1, n + 1))
    qualified = tuple(frozenset(group) for group in combinations(people, k))
    forbidden = tuple(frozenset(group) for group in combinations(people, k - 1))
    return people, qualified, forbidden

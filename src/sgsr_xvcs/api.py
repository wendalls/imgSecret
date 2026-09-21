"""Stable public API for SARR and the conflict-pruned Shen baseline."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from time import perf_counter

from .core import Participant, _set_mask, normalise_access_structure
from .sgsr import optimize_sgsr
from .shen import EnumerationLimitExceeded, optimize_pruned_paper_method
from .tables import ShareTableOptimizationResult, _threshold_parameters
from .threshold import MAX_PARTICIPANTS, optimize_threshold


@dataclass(frozen=True)
class GeneralResult:
    participant_count: int
    minimal_qualified_count: int
    qualified_target_count: int
    reconstruction_mode: str
    optimal_regions: int
    elapsed_seconds: float
    examined_pairs: int
    raw_candidates: int
    deduplicated_candidates: int
    nondominated_candidates: int
    solver: str
    detail: ShareTableOptimizationResult

    def to_dict(self) -> dict:
        return {
            "participant_count": self.participant_count,
            "minimal_qualified_count": self.minimal_qualified_count,
            "qualified_target_count": self.qualified_target_count,
            "reconstruction_mode": self.reconstruction_mode,
            "optimal_regions": self.optimal_regions,
            "elapsed_seconds": self.elapsed_seconds,
            "examined_pairs": self.examined_pairs,
            "raw_candidates": self.raw_candidates,
            "deduplicated_candidates": self.deduplicated_candidates,
            "nondominated_candidates": self.nondominated_candidates,
            "solver": self.solver,
        }


@dataclass(frozen=True)
class ShenSummary:
    completed: bool
    elapsed_seconds: float
    optimal_regions: int | None
    compatibility_checks: int
    visited_nodes: int
    maximal_groups: int | None
    message: str


@dataclass(frozen=True)
class ComparisonResult:
    structure_kind: str
    same_optimum: bool | None
    sgsr: dict
    shen_pruned: ShenSummary

    def to_dict(self) -> dict:
        return {
            "structure_kind": self.structure_kind,
            "same_optimum": self.same_optimum,
            "sgsr": self.sgsr,
            "shen_pruned": asdict(self.shen_pruned),
        }


def optimize_general(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
    reconstruction_mode: str = "standard",
) -> GeneralResult:
    """Solve a general access structure exactly with SARR recovery semantics."""
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    if len(people) > MAX_PARTICIPANTS:
        raise ValueError(f"this release supports n <= {MAX_PARTICIPANTS}")
    index = {participant: position for position, participant in enumerate(people)}
    q_masks = tuple(_set_mask(group, index) for group in q_min)
    f_masks = tuple(_set_mask(group, index) for group in f_max)
    mode = reconstruction_mode.lower()
    if mode not in {"standard", "mi", "mifr"}:
        raise ValueError("reconstruction_mode must be standard, mi, or mifr")
    if mode == "standard" and _threshold_parameters(q_masks, f_masks, len(people)) is not None:
        raise ValueError("use optimize_threshold for a complete (k,n) structure")
    started = perf_counter()
    result = optimize_sgsr(
        q_min,
        f_max,
        participants=people,
        max_share_types=max_share_types,
        max_candidate_pairs=max_candidate_pairs,
        ilp_backend=ilp_backend,
        reconstruction_mode=mode,
    )
    elapsed = perf_counter() - started
    return GeneralResult(
        len(people),
        len(q_min),
        len(result.scheme.minimal_qualified),
        mode,
        result.scheme.pixel_expansion,
        elapsed,
        result.scheme.compatibility_checks,
        result.raw_candidate_count,
        result.deduplicated_candidate_count,
        result.nondominated_candidate_count,
        result.solver,
        result,
    )


def optimize_access_structure(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    ilp_backend: str = "auto",
    threshold_time_limit_seconds: float | None = None,
    reconstruction_mode: str = "standard",
):
    """Automatically dispatch to the general or complete-threshold solver."""
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    if len(people) > MAX_PARTICIPANTS:
        raise ValueError(f"this release supports n <= {MAX_PARTICIPANTS}")
    index = {participant: position for position, participant in enumerate(people)}
    q_masks = tuple(_set_mask(group, index) for group in q_min)
    f_masks = tuple(_set_mask(group, index) for group in f_max)
    threshold = _threshold_parameters(q_masks, f_masks, len(people))
    mode = reconstruction_mode.lower()
    if threshold is not None and mode == "standard":
        k, n = threshold
        return optimize_threshold(k, n, time_limit_seconds=threshold_time_limit_seconds)
    return optimize_general(
        q_min,
        f_max,
        participants=people,
        max_share_types=max_share_types,
        max_candidate_pairs=max_candidate_pairs,
        ilp_backend=ilp_backend,
        reconstruction_mode=mode,
    )


def compare_with_shen(
    qualified: Iterable[Iterable[Participant]],
    forbidden: Iterable[Iterable[Participant]],
    *,
    participants: Iterable[Participant] | None = None,
    max_share_types: int | None = None,
    max_candidate_pairs: int = 2_000_000,
    shen_max_checks: int = 5_000_000,
    shen_max_nodes: int | None = 250_000,
    ilp_backend: str = "auto",
    threshold_time_limit_seconds: float | None = None,
) -> ComparisonResult:
    """Run SARR and the conflict-pruned Shen method on the same structure.

    A resource-limited Shen run is reported as incomplete and is never used as
    an optimum or timing comparison.
    """
    people, q_min, f_max = normalise_access_structure(qualified, forbidden, participants)
    index = {participant: position for position, participant in enumerate(people)}
    q_masks = tuple(_set_mask(group, index) for group in q_min)
    f_masks = tuple(_set_mask(group, index) for group in f_max)
    threshold = _threshold_parameters(q_masks, f_masks, len(people))

    if threshold is None:
        sgsr_result = optimize_general(
            q_min,
            f_max,
            participants=people,
            max_share_types=max_share_types,
            max_candidate_pairs=max_candidate_pairs,
            ilp_backend=ilp_backend,
        )
        sgsr_summary = sgsr_result.to_dict()
        sgsr_optimum = sgsr_result.optimal_regions
        structure_kind = "general"
    else:
        k, n = threshold
        threshold_result = optimize_threshold(
            k, n, time_limit_seconds=threshold_time_limit_seconds
        )
        sgsr_summary = threshold_result.to_dict()
        sgsr_optimum = threshold_result.optimal_regions
        structure_kind = f"threshold({k},{n})"

    shen_started = perf_counter()
    try:
        shen = optimize_pruned_paper_method(
            q_min,
            f_max,
            participants=people,
            max_compatibility_checks=shen_max_checks,
            max_visited_nodes=shen_max_nodes,
            ilp_backend=ilp_backend,
        )
        shen_elapsed = perf_counter() - shen_started
        shen_optimum = shen.optimization.scheme.pixel_expansion
        shen_summary = ShenSummary(
            True,
            shen_elapsed,
            shen_optimum,
            shen.enumeration.compatibility_checks,
            shen.enumeration.visited_nodes,
            len(shen.enumeration.maximal_group_masks),
            "completed",
        )
        same = sgsr_optimum == shen_optimum if sgsr_optimum is not None else None
    except EnumerationLimitExceeded as error:
        shen_summary = ShenSummary(
            False,
            error.elapsed_seconds,
            None,
            error.compatibility_checks,
            error.visited_nodes,
            None,
            str(error),
        )
        same = None
    return ComparisonResult(structure_kind, same, sgsr_summary, shen_summary)

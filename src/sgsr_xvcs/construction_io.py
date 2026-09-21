"""Portable JSON serialization for optimized SARR constructions."""

from __future__ import annotations

import json
from pathlib import Path

from .api import GeneralResult
from .core import AllocationBlock, LinearShareFormula, ShareReuseScheme
from .threshold import ThresholdResult

FORMAT = "sgsr-xvcs-construction-v1"


def _general_payload(result: GeneralResult) -> dict:
    scheme = result.detail.scheme
    participants = list(scheme.participants)
    return {
        "format": FORMAT,
        "kind": "general",
        "summary": result.to_dict(),
        "construction": {
            "participants": participants,
            "minimal_qualified": [list(group) for group in scheme.minimal_qualified],
            "maximal_forbidden": [list(group) for group in scheme.maximal_forbidden],
            "method": scheme.method,
            "optimal": scheme.optimal,
            "compatibility_checks": scheme.compatibility_checks,
            "reconstruction_mode": scheme.reconstruction_mode,
            "regions": [
                {
                    "block_id": block.block_id,
                    "recovered_qualified": [
                        list(group) for group in block.recovered_qualified
                    ],
                    "rank": block.rank,
                    "random_variable_count": block.random_variable_count,
                    "formulas": [
                        {
                            "participant": participant,
                            "secret_coefficient": block.share_formulas[
                                participant
                            ].secret_coefficient,
                            "random_terms": list(
                                block.share_formulas[participant].random_terms
                            ),
                        }
                        for participant in scheme.participants
                    ],
                }
                for block in scheme.blocks
            ],
        },
    }


def _threshold_payload(result: ThresholdResult) -> dict:
    return {
        "format": FORMAT,
        "kind": "threshold",
        "summary": result.to_dict(),
        "construction": {
            "k": result.k,
            "n": result.n,
            "share_type_formulas": list(result.share_type_formulas),
            "selected_candidate_indices": list(result.selected_candidate_indices),
            "selected_assignments": [
                list(assignment) for assignment in result.selected_assignments
            ],
        },
    }


def construction_payload(result: GeneralResult | ThresholdResult) -> dict:
    """Convert an optimization result to a portable JSON-compatible payload."""
    if isinstance(result, GeneralResult):
        return _general_payload(result)
    if isinstance(result, ThresholdResult):
        return _threshold_payload(result)
    raise TypeError(f"unsupported optimization result: {type(result).__name__}")


def save_construction(result: GeneralResult | ThresholdResult, path) -> Path:
    """Save a complete optimized construction and return its path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(construction_payload(result), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _load_general(payload: dict) -> ShareReuseScheme:
    data = payload["construction"]
    participants = tuple(data["participants"])
    blocks = []
    for region in data["regions"]:
        formulas = {
            item["participant"]: LinearShareFormula(
                int(item["secret_coefficient"]), tuple(item["random_terms"])
            )
            for item in region["formulas"]
        }
        blocks.append(
            AllocationBlock(
                int(region["block_id"]),
                tuple(frozenset(group) for group in region["recovered_qualified"]),
                formulas,
                int(region["rank"]),
                int(region["random_variable_count"]),
            )
        )
    return ShareReuseScheme(
        participants,
        tuple(frozenset(group) for group in data["minimal_qualified"]),
        tuple(frozenset(group) for group in data["maximal_forbidden"]),
        blocks,
        data["method"],
        bool(data["optimal"]),
        int(data["compatibility_checks"]),
        data["reconstruction_mode"],
    )


def _load_threshold(payload: dict) -> ThresholdResult:
    summary = payload["summary"]
    data = payload["construction"]
    return ThresholdResult(
        k=int(data["k"]),
        n=int(data["n"]),
        qualified_count=int(summary["qualified_count"]),
        raw_candidate_count=int(summary["raw_candidate_count"]),
        candidate_count=int(summary["candidate_count"]),
        duplicate_candidates_removed=int(summary["duplicate_candidates_removed"]),
        dominated_candidates_removed=int(summary["dominated_candidates_removed"]),
        matrix_nonzeros=int(summary["matrix_nonzeros"]),
        matrix_density=float(summary["matrix_density"]),
        matrix_generation_seconds=float(summary["matrix_generation_seconds"]),
        solver_seconds=float(summary["solver_seconds"]),
        solver_status=summary["solver_status"],
        proven_optimal=bool(summary["proven_optimal"]),
        lower_bound=int(summary["lower_bound"]),
        upper_bound=int(summary["upper_bound"]),
        optimal_regions=(
            None if summary["optimal_regions"] is None else int(summary["optimal_regions"])
        ),
        selected_candidate_indices=tuple(data["selected_candidate_indices"]),
        selected_assignments=tuple(tuple(row) for row in data["selected_assignments"]),
        share_type_formulas=tuple(data["share_type_formulas"]),
        solver_threads=int(summary.get("solver_threads", 1)),
        solver_parallel=bool(summary.get("solver_parallel", False)),
    )


def load_construction(path) -> ShareReuseScheme | ThresholdResult:
    """Load and validate a construction file for image encoding."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("format") != FORMAT:
        raise ValueError("unsupported construction format")
    if payload.get("kind") == "general":
        return _load_general(payload)
    if payload.get("kind") == "threshold":
        return _load_threshold(payload)
    raise ValueError(f"unsupported construction kind: {payload.get('kind')!r}")

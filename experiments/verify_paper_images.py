"""Verify the whole expanded XOR images used in the manuscript examples."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT.parent / "paper_assets" if ROOT.name == "code" else ROOT / "paper_assets"


def _bits(path: Path) -> np.ndarray:
    return (np.asarray(Image.open(path).convert("L"), dtype=np.uint8) < 128).astype(np.uint8)


def _region(directory: Path, participant: int, region: int, expansion: int) -> np.ndarray:
    expanded = _bits(directory / f"share_{participant:03d}.png")
    width = expanded.shape[1] // expansion
    return expanded[:, region * width : (region + 1) * width]


def _xor(directory: Path, coalition: tuple[int, ...], region: int, expansion: int) -> np.ndarray:
    output = np.zeros_like(_region(directory, coalition[0], region, expansion))
    for participant in coalition:
        output ^= _region(directory, participant, region, expansion)
    return output


def _xor_expanded(directory: Path, coalition: tuple[int, ...]) -> np.ndarray:
    output = np.zeros_like(_bits(directory / f"share_{coalition[0]:03d}.png"))
    for participant in coalition:
        output ^= _bits(directory / f"share_{participant:03d}.png")
    return output


def main() -> None:
    general = ASSETS / "general_n5_mixed" / "images"
    general_secret = _bits(general / "secret_binary.png")
    general_coalitions = ((1, 2), (1, 3), (1, 4, 5), (2, 3, 4), (2, 3, 5))
    expected_general = (
        (True, True),
        (True, False),
        (True, False),
        (False, True),
        (False, True),
    )
    observed_general = tuple(
        tuple(
            bool(np.array_equal(_xor(general, coalition, region, 2), general_secret))
            for region in range(2)
        )
        for coalition in general_coalitions
    )
    if observed_general != expected_general:
        raise AssertionError(f"mixed example mismatch: {observed_general}")
    general_whole_shapes = tuple(
        tuple(_xor_expanded(general, coalition).shape[::-1]) for coalition in general_coalitions
    )
    if set(general_whole_shapes) != {(1024, 512)}:
        raise AssertionError(f"mixed whole-image dimensions mismatch: {general_whole_shapes}")

    threshold = ASSETS / "threshold_3_6"
    threshold_secret = _bits(threshold / "secret_binary.png")
    threshold_coalitions = ((1, 3, 5), (1, 2, 4), (1, 2, 3))
    expected_threshold = (
        (True, False, False),
        (False, True, False),
        (False, False, True),
    )
    observed_threshold = tuple(
        tuple(
            bool(np.array_equal(_xor(threshold, coalition, region, 3), threshold_secret))
            for region in range(3)
        )
        for coalition in threshold_coalitions
    )
    if observed_threshold != expected_threshold:
        raise AssertionError(f"threshold example mismatch: {observed_threshold}")
    threshold_whole_shapes = tuple(
        tuple(_xor_expanded(threshold, coalition).shape[::-1]) for coalition in threshold_coalitions
    )
    if set(threshold_whole_shapes) != {(1536, 512)}:
        raise AssertionError(f"threshold whole-image dimensions mismatch: {threshold_whole_shapes}")

    metadata = json.loads((threshold / "metadata.json").read_text(encoding="utf-8"))
    assignments = [entry["allocation"] for entry in metadata["regions"]]
    random_mask_hashes = []
    for region, labels in enumerate(assignments):
        participant = labels.index(0) + 1
        mask = _region(threshold, participant, region, 3)
        random_mask_hashes.append(hashlib.sha256(mask.tobytes()).hexdigest())
    if len(set(random_mask_hashes)) != 3:
        raise AssertionError("threshold regions do not use distinct first random masks")

    report = {
        "secret_dimensions": list(general_secret.shape[::-1]),
        "mixed_general_access": {
            "coalitions": [list(group) for group in general_coalitions],
            "whole_xor_dimensions": [list(shape) for shape in general_whole_shapes],
            "region_equals_secret": observed_general,
        },
        "threshold_3_6": {
            "coalitions": [list(group) for group in threshold_coalitions],
            "whole_xor_dimensions": [list(shape) for shape in threshold_whole_shapes],
            "region_equals_secret": observed_threshold,
            "independent_first_mask_hashes": random_mask_hashes,
        },
    }
    output = ROOT / "results" / "paper_image_verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

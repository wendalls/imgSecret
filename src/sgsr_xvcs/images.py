"""Binary image encoding and reconstruction for SGSR constructions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

from .api import GeneralResult
from .core import ShareReuseScheme, generate_binary_shares
from .threshold import ThresholdResult


def load_binary_image(path, *, threshold: int = 128, invert: bool = False) -> np.ndarray:
    """Load an image as bits, using 1 for black and 0 for white."""
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be between 0 and 255")
    gray = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    bits = (gray < threshold).astype(np.uint8)
    return bits ^ np.uint8(bool(invert))


def save_binary_image(bits, path) -> Path:
    """Save a bit array as a black-white PNG."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    array = np.asarray(bits, dtype=np.uint8) & 1
    Image.fromarray(np.where(array, 0, 255).astype(np.uint8), mode="L").save(output)
    return output


def _expanded_image(region_stack: np.ndarray) -> np.ndarray:
    if region_stack.ndim != 3:
        raise ValueError("share stack must have shape (height, width, regions)")
    height, width, regions = region_stack.shape
    # Store complete region images as contiguous horizontal blocks:
    # [region 1 | region 2 | ... | region m].
    return region_stack.transpose(0, 2, 1).reshape(height, width * regions)


def _stack_from_image(
    path: Path,
    width: int,
    regions: int,
    *,
    layout: str = "interleaved_columns",
) -> np.ndarray:
    expanded = load_binary_image(path)
    if expanded.shape[1] != width * regions:
        raise ValueError(f"unexpected share width in {path}")
    if layout == "horizontal_region_blocks":
        return expanded.reshape(expanded.shape[0], regions, width).transpose(0, 2, 1)
    if layout == "interleaved_columns":
        # Backward compatibility for image metadata written before v2.
        return expanded.reshape(expanded.shape[0], width, regions)
    raise ValueError(f"unsupported region layout: {layout}")


def _participant_records(participants, output_dir: Path, stacks) -> list[dict]:
    records = []
    for position, participant in enumerate(participants):
        filename = f"share_{position + 1:03d}.png"
        save_binary_image(_expanded_image(stacks[participant]), output_dir / filename)
        records.append({
            "index": position,
            "label": str(participant),
            "file": filename,
        })
    return records


def encode_general_image(
    secret_path,
    construction: GeneralResult | ShareReuseScheme,
    output_dir,
    *,
    seed: int | None = None,
    threshold: int = 128,
) -> Path:
    """Encode a binary image with a solved general-access SGSR scheme."""
    scheme = construction.detail.scheme if isinstance(construction, GeneralResult) else construction
    secret = load_binary_image(secret_path, threshold=threshold)
    rng = np.random.default_rng(seed)
    stacks = generate_binary_shares(secret, scheme, rng=rng)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    save_binary_image(secret, target / "secret_binary.png")
    records = _participant_records(scheme.participants, target, stacks)
    position = {participant: index for index, participant in enumerate(scheme.participants)}
    metadata = {
        "format": "sgsr-xvcs-image-v2",
        "kind": "general",
        "region_layout": "horizontal_region_blocks",
        "reconstruction_mode": scheme.reconstruction_mode,
        "mifr_full_region": (
            scheme.pixel_expansion - 1 if scheme.reconstruction_mode == "mifr" else None
        ),
        "height": int(secret.shape[0]),
        "width": int(secret.shape[1]),
        "pixel_expansion": scheme.pixel_expansion,
        "participants": records,
        "regions": [
            {
                "index": block.block_id - 1,
                "recovery_groups": [
                    [position[participant] for participant in group]
                    for group in block.recovered_qualified
                ],
            }
            for block in scheme.blocks
        ],
    }
    (target / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target / "metadata.json"


def _threshold_stacks(secret: np.ndarray, result: ThresholdResult, seed: int | None):
    rng = np.random.default_rng(seed)
    stacks = {participant: [] for participant in range(result.n)}
    for labels in result.selected_assignments:
        randoms = [
            rng.integers(0, 2, size=secret.shape, dtype=np.uint8)
            for _ in range(result.k - 1)
        ]
        types = list(randoms)
        final_type = secret.copy()
        for random_image in randoms:
            final_type ^= random_image
        types.append(final_type)
        for participant, label in enumerate(labels):
            stacks[participant].append(types[label])
    return {
        participant: np.stack(regions, axis=-1)
        for participant, regions in stacks.items()
    }


def encode_threshold_image(
    secret_path,
    result: ThresholdResult,
    output_dir,
    *,
    seed: int | None = None,
    threshold: int = 128,
) -> Path:
    """Encode a binary image using a solved complete threshold construction."""
    if not result.selected_assignments:
        raise ValueError("threshold result has no feasible selected assignments")
    secret = load_binary_image(secret_path, threshold=threshold)
    stacks = _threshold_stacks(secret, result, seed)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    save_binary_image(secret, target / "secret_binary.png")
    records = _participant_records(tuple(range(result.n)), target, stacks)
    for record in records:
        record["label"] = str(record["index"] + 1)
    metadata = {
        "format": "sgsr-xvcs-image-v2",
        "kind": "threshold",
        "region_layout": "horizontal_region_blocks",
        "k": result.k,
        "n": result.n,
        "height": int(secret.shape[0]),
        "width": int(secret.shape[1]),
        "pixel_expansion": len(result.selected_assignments),
        "participants": records,
        "regions": [
            {"index": index, "allocation": list(labels)}
            for index, labels in enumerate(result.selected_assignments)
        ],
    }
    (target / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target / "metadata.json"


def _load_share_stacks(directory: Path, metadata: dict) -> dict[int, np.ndarray]:
    return {
        record["index"]: _stack_from_image(
            directory / record["file"],
            metadata["width"],
            metadata["pixel_expansion"],
            layout=metadata.get("region_layout", "interleaved_columns"),
        )
        for record in metadata["participants"]
    }


def reconstruct_from_directory(
    directory,
    coalition: Iterable[str | int],
    *,
    output_name: str = "reconstructed.png",
) -> Path:
    """Reconstruct one secret image from saved shares and metadata.

    For nonmonotone XOR schemes, the function automatically selects a minimal
    recovering subset contained in the supplied coalition instead of XORing
    every supplied share.
    """
    root = Path(directory)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    wanted_labels = {str(item) for item in coalition}
    label_to_index = {
        record["label"]: record["index"] for record in metadata["participants"]
    }
    try:
        supplied = {label_to_index[label] for label in wanted_labels}
    except KeyError as error:
        raise ValueError(f"unknown participant label: {error.args[0]}") from error
    stacks = _load_share_stacks(root, metadata)

    selected_group = None
    selected_region = None
    if metadata["kind"] == "general":
        exact_group = metadata.get("reconstruction_mode", "standard") in {"mi", "mifr"}
        regions = metadata["regions"]
        mifr_region = metadata.get("mifr_full_region")
        if mifr_region is not None and supplied == set(stacks):
            # Prefer the dedicated appended MIFR region for full-set recovery.
            regions = sorted(regions, key=lambda item: item["index"] != mifr_region)
        for region in regions:
            for group in region["recovery_groups"]:
                if (set(group) == supplied) if exact_group else (set(group) <= supplied):
                    selected_group = tuple(group)
                    selected_region = region["index"]
                    break
            if selected_group is not None:
                break
    elif metadata["kind"] == "threshold":
        k = metadata["k"]
        for region in metadata["regions"]:
            labels = region["allocation"]
            for group in combinations(sorted(supplied), k):
                if len({labels[index] for index in group}) == k:
                    selected_group = group
                    selected_region = region["index"]
                    break
            if selected_group is not None:
                break

    else:
        raise ValueError(f"unsupported image metadata kind: {metadata['kind']}")

    if selected_group is None or selected_region is None:
        raise ValueError("the supplied coalition is not qualified by this construction")
    recovered = np.zeros(
        (metadata["height"], metadata["width"]), dtype=np.uint8
    )
    for participant in selected_group:
        recovered ^= stacks[participant][..., selected_region]
    return save_binary_image(recovered, root / output_name)


def reconstruct_expanded_from_directory(
    directory,
    coalition: Iterable[str | int],
    *,
    output_name: str = "coalition_xor.png",
) -> Path:
    """XOR complete expanded shares and save one whole coalition image.

    The output has the same dimensions as each expanded participant share:
    ``height`` by ``width * pixel_expansion``. Complete region images are
    concatenated horizontally in region order; no region is saved separately.
    """
    root = Path(directory)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    wanted_labels = {str(item) for item in coalition}
    label_to_index = {
        record["label"]: record["index"] for record in metadata["participants"]
    }
    try:
        supplied = tuple(sorted(label_to_index[label] for label in wanted_labels))
    except KeyError as error:
        raise ValueError(f"unknown participant label: {error.args[0]}") from error
    if not supplied:
        raise ValueError("coalition must contain at least one participant")

    stacks = _load_share_stacks(root, metadata)
    recovered = np.zeros(
        (
            metadata["height"],
            metadata["width"],
            metadata["pixel_expansion"],
        ),
        dtype=np.uint8,
    )
    for participant in supplied:
        recovered ^= stacks[participant]
    return save_binary_image(_expanded_image(recovered), root / output_name)

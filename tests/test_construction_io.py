from pathlib import Path

import numpy as np

from sgsr_xvcs import (
    encode_general_image,
    encode_threshold_image,
    load_binary_image,
    load_construction,
    maximal_forbidden,
    optimize_general,
    optimize_threshold,
    reconstruct_from_directory,
    save_binary_image,
    save_construction,
)
from sgsr_xvcs.core import ShareReuseScheme
from sgsr_xvcs.threshold import ThresholdResult


def _secret(path: Path) -> np.ndarray:
    bits = np.asarray(
        [[0, 1, 0, 1], [1, 1, 0, 0], [0, 0, 1, 1]], dtype=np.uint8
    )
    save_binary_image(bits, path)
    return bits


def test_general_construction_round_trip(tmp_path):
    participants = (1, 2, 3, 4)
    qualified = ({1, 2}, {1, 3, 4})
    result = optimize_general(
        qualified,
        maximal_forbidden(participants, qualified),
        participants=participants,
    )
    construction_path = save_construction(result, tmp_path / "general.json")
    loaded = load_construction(construction_path)
    assert isinstance(loaded, ShareReuseScheme)

    secret = _secret(tmp_path / "secret.png")
    output = tmp_path / "general_shares"
    encode_general_image(tmp_path / "secret.png", loaded, output, seed=7)
    recovered = reconstruct_from_directory(output, (1, 2))
    np.testing.assert_array_equal(load_binary_image(recovered), secret)


def test_threshold_construction_round_trip(tmp_path):
    result = optimize_threshold(2, 3, workers=2)
    construction_path = save_construction(result, tmp_path / "threshold.json")
    loaded = load_construction(construction_path)
    assert isinstance(loaded, ThresholdResult)

    secret = _secret(tmp_path / "secret.png")
    output = tmp_path / "threshold_shares"
    encode_threshold_image(tmp_path / "secret.png", loaded, output, seed=7)
    recovered = reconstruct_from_directory(output, (1, 2))
    np.testing.assert_array_equal(load_binary_image(recovered), secret)

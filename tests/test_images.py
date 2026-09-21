import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from sgsr_xvcs import (
    encode_general_image,
    encode_threshold_image,
    load_binary_image,
    maximal_forbidden,
    optimize_general,
    optimize_threshold,
    reconstruct_expanded_from_directory,
    reconstruct_from_directory,
    save_binary_image,
)


class ImageTests(unittest.TestCase):
    @staticmethod
    def _secret():
        rows, columns = np.indices((12, 16))
        return ((rows // 3 + columns // 4) % 2).astype(np.uint8)

    def test_general_image_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = save_binary_image(self._secret(), root / "secret.png")
            people = (1, 2, 3, 4)
            qualified = ({1, 2}, {1, 3, 4})
            forbidden = maximal_forbidden(people, qualified)
            result = optimize_general(qualified, forbidden, participants=people)
            output = root / "general"
            encode_general_image(source, result, output, seed=7)
            recovered = reconstruct_from_directory(output, (1, 2))
            np.testing.assert_array_equal(
                load_binary_image(recovered), load_binary_image(source)
            )

    def test_threshold_image_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = save_binary_image(self._secret(), root / "secret.png")
            result = optimize_threshold(2, 4, time_limit_seconds=30)
            output = root / "threshold"
            encode_threshold_image(source, result, output, seed=11)
            recovered = reconstruct_from_directory(output, (1, 2, 3, 4))
            np.testing.assert_array_equal(
                load_binary_image(recovered), load_binary_image(source)
            )

    def test_forbidden_coalition_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = save_binary_image(self._secret(), root / "secret.png")
            result = optimize_threshold(3, 5, time_limit_seconds=30)
            output = root / "threshold"
            encode_threshold_image(source, result, output, seed=13)
            with self.assertRaisesRegex(ValueError, "not qualified"):
                reconstruct_from_directory(output, (1, 2))

    def test_expanded_xor_is_one_whole_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = save_binary_image(self._secret(), root / "secret.png")
            result = optimize_threshold(3, 6, time_limit_seconds=30)
            output = root / "threshold"
            encode_threshold_image(source, result, output, seed=17)
            recovered = reconstruct_expanded_from_directory(output, (1, 3, 5))
            expanded = load_binary_image(recovered)
            self.assertEqual(
                expanded.shape,
                (self._secret().shape[0], self._secret().shape[1] * result.optimal_regions),
            )
            width = self._secret().shape[1]
            np.testing.assert_array_equal(
                expanded[:, :width], load_binary_image(source)
            )
            metadata = json.loads(
                (output / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["region_layout"], "horizontal_region_blocks")


if __name__ == "__main__":
    unittest.main()

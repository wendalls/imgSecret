import importlib.util
import unittest

from sgsr_xvcs import build_threshold_incidence_matrix, optimize_threshold


class ThresholdTests(unittest.TestCase):
    def test_n10_matrix_is_supported(self):
        qualified, assignments, coverage = build_threshold_incidence_matrix(2, 10)
        self.assertEqual(len(qualified), 45)
        self.assertEqual(len(assignments), 511)  # S(10,2)
        self.assertEqual(len(coverage), 511)
        self.assertTrue(all(mask for mask in coverage))

    def test_n11_is_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, "n <= 10"):
            build_threshold_incidence_matrix(2, 11)

    @unittest.skipUnless(importlib.util.find_spec("ortools"), "OR-Tools not installed")
    def test_threshold_24_optimum(self):
        result = optimize_threshold(2, 4, time_limit_seconds=30)
        self.assertTrue(result.proven_optimal)
        self.assertEqual(result.optimal_regions, 2)
        self.assertEqual(result.raw_candidate_count, result.candidate_count)
        self.assertEqual(result.duplicate_candidates_removed, 0)
        # Transversal coverage domains of canonical k-partitions do not dominate.
        self.assertEqual(result.dominated_candidates_removed, 0)

    @unittest.skipUnless(importlib.util.find_spec("ortools"), "OR-Tools not installed")
    def test_threshold_2_10_optimum(self):
        result = optimize_threshold(2, 10, time_limit_seconds=30)
        self.assertTrue(result.proven_optimal)
        self.assertEqual(result.optimal_regions, 4)


if __name__ == "__main__":
    unittest.main()

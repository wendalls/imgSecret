import unittest

from sgsr_xvcs import compare_with_shen, maximal_forbidden, optimize_general


class GeneralTests(unittest.TestCase):
    def test_one_region_structure(self):
        people = (1, 2, 3, 4)
        qualified = ({1, 2}, {1, 3, 4})
        forbidden = maximal_forbidden(people, qualified)
        result = optimize_general(qualified, forbidden, participants=people)
        self.assertEqual(result.optimal_regions, 1)
        self.assertLessEqual(result.deduplicated_candidates, result.raw_candidates)
        self.assertLessEqual(
            result.nondominated_candidates,
            result.deduplicated_candidates,
        )

    def test_sgsr_and_shen_agree(self):
        people = (1, 2, 3, 4)
        qualified = ({1, 2}, {2, 3}, {3, 4})
        forbidden = maximal_forbidden(people, qualified)
        result = compare_with_shen(
            qualified,
            forbidden,
            participants=people,
            shen_max_nodes=100_000,
        )
        self.assertTrue(result.shen_pruned.completed)
        self.assertTrue(result.same_optimum)
        self.assertEqual(result.sgsr["optimal_regions"], 2)
        self.assertLess(
            result.sgsr["nondominated_candidates"],
            result.sgsr["raw_candidates"],
        )

    def test_shen_limit_is_reported_as_incomplete(self):
        people = (1, 2, 3, 4)
        qualified = ({1, 2}, {2, 3}, {3, 4})
        forbidden = maximal_forbidden(people, qualified)
        result = compare_with_shen(
            qualified,
            forbidden,
            participants=people,
            shen_max_checks=1,
            shen_max_nodes=100_000,
        )
        self.assertFalse(result.shen_pruned.completed)
        self.assertIsNone(result.same_optimum)

    def test_mi_and_mifr_recovery_modes(self):
        people = (1, 2, 3)
        qualified = ({1, 2},)
        forbidden = maximal_forbidden(people, qualified)
        mi = optimize_general(
            qualified, forbidden, participants=people, reconstruction_mode="mi"
        )
        mifr = optimize_general(
            qualified, forbidden, participants=people, reconstruction_mode="mifr"
        )
        self.assertEqual(mi.qualified_target_count, 2)
        self.assertEqual(set(mi.detail.scheme.minimal_qualified), {
            frozenset({1, 2}), frozenset({1, 2, 3})
        })
        self.assertEqual(mifr.optimal_regions, mi.optimal_regions + 1)
        self.assertEqual(
            mifr.detail.scheme.blocks[-1].recovered_qualified,
            (frozenset(people),),
        )


if __name__ == "__main__":
    unittest.main()

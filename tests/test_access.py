import unittest

from sgsr_xvcs import maximal_forbidden, threshold_access_structure


class AccessTests(unittest.TestCase):
    def test_maximal_forbidden(self):
        result = set(maximal_forbidden((1, 2, 3, 4), ({1, 2}, {1, 3, 4})))
        self.assertEqual(
            result,
            {frozenset({1, 3}), frozenset({1, 4}), frozenset({2, 3, 4})},
        )

    def test_threshold_access(self):
        people, qualified, forbidden = threshold_access_structure(3, 6)
        self.assertEqual(len(people), 6)
        self.assertEqual(len(qualified), 20)
        self.assertEqual(len(forbidden), 15)


if __name__ == "__main__":
    unittest.main()

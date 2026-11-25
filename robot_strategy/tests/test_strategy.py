import unittest
from robot_strategy.strategy import candidates, suggest, truth, answer_suggestion


class StrategyTests(unittest.TestCase):
    def test_strict_comparisons(self):
        self.assertFalse(truth(5, 'gt', 5))
        self.assertFalse(truth(5, 'lt', 5))
        self.assertTrue(truth(5, 'eq', 5))

    def test_one_lie_retained_two_excluded(self):
        h = [dict(kind='gt', number=5, answer=True)]
        self.assertEqual(dict(candidates(h))[3], 1)
        self.assertNotIn(3, dict(candidates(h * 2)))

    def test_contradiction_and_exhaustion(self):
        h = [dict(kind='eq', number=n, answer=True) for n in (1, 2, 3)]
        self.assertEqual(suggest(h, 4)['status'], 'inconsistent')
        h = [dict(kind='gt', number=10, answer=False)] * 7
        self.assertEqual(suggest(h, 0)['status'], 'insufficient')

    def test_reject_invalid(self):
        for n in (True, 0, 11, 5.0):
            with self.assertRaises(ValueError):
                truth(5, 'gt', n)
        for answer in (1, 'false', None):
            with self.assertRaises(ValueError):
                candidates([dict(kind='eq', number=5, answer=answer)])
        with self.assertRaises(ValueError):
            suggest([], 6)

    def test_answer_budget_and_retry(self):
        self.assertEqual(answer_suggestion(7, 'gt', 5), {'answer': True, 'uses_lie': False})
        self.assertEqual(answer_suggestion(7, 'gt', 5, use_lie=True),
                         answer_suggestion(7, 'gt', 5, use_lie=True))
        with self.assertRaises(ValueError):
            answer_suggestion(7, 'gt', 5, 1, True)


if __name__ == '__main__':
    unittest.main()

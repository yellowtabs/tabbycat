from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from adjfeedback.utils import feedback_stats


class FeedbackTrendTests(SimpleTestCase):

    def test_cumulative_average_uses_submission_counts_and_excludes_base(self):
        rounds = [Mock(seq=i, id=i) for i in range(1, 4)]
        feedbacks = [SimpleNamespace(round=rounds[0], score=8)]
        feedbacks += [SimpleNamespace(round=rounds[2], score=4) for _ in range(10)]
        adjudicator = SimpleNamespace(
            base_score=7,
            adjfeedback_for_rounds=feedbacks,
            debateadjs_for_rounds=[],
        )

        points = feedback_stats(adjudicator, rounds)

        self.assertEqual([point['x'] for point in points], [1, 3])
        self.assertEqual([point['count'] for point in points], [1, 10])
        self.assertEqual([point['y'] for point in points], [8, 4])
        self.assertEqual([point['cumulative'] for point in points], [8, 4.36])
        self.assertEqual([point['cumulative_count'] for point in points], [1, 11])

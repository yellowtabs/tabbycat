from django.test import SimpleTestCase

from adjfeedback.tables import FeedbackTableBuilder


class FeedbackScoreFormattingTestCase(SimpleTestCase):

    def test_preserves_up_to_three_decimal_places(self):
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4.125), '4.125')
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4.1), '4.1')
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4), '4.0')

    def test_strong_score_preserves_precision(self):
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4.125, strong=True), '<strong>4.125</strong>')

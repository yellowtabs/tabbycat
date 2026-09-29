from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from adjfeedback.tables import FeedbackTableBuilder


class FeedbackScoreFormattingTestCase(SimpleTestCase):

    def test_preserves_up_to_three_decimal_places(self):
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4.125), '4.125')
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4.1), '4.1')
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4), '4.0')

    def test_strong_score_preserves_precision(self):
        self.assertEqual(FeedbackTableBuilder.get_formatted_adj_score(4.125, strong=True), '<strong>4.125</strong>')


class FeedbackAdjudicatorLinkTestCase(SimpleTestCase):

    @patch('utils.tables.has_permission', return_value=False)
    def test_name_links_to_record_when_requested(self, _has_permission):
        tournament = SimpleNamespace(slug='test', pref=Mock(side_effect={
            'teams_in_debate': 2,
            'show_adjudicator_institutions': False,
            'show_unaccredited': False,
        }.get))
        adjudicator = SimpleNamespace(
            pk=1, name='Test Adjudicator', anonymous=False, institution=None,
            adj_core=False, independent=False,
            get_public_name=lambda tournament: 'Test Adjudicator',
        )
        table = FeedbackTableBuilder(tournament=tournament, admin=True)

        table.add_adjudicator_columns([adjudicator], show_institutions=False,
                                      link_to_record=True)

        cell = table.jsondict()['data'][0][0]
        self.assertEqual(cell['link'], '/test/admin/participants/adjudicator/1/')
        self.assertEqual(cell['popover']['content'][0]['link'], cell['link'])

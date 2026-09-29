from django.test import TestCase

from participants.models import Adjudicator, Institution, Team
from participants.views import InstitutionAdjRuleView
from tournaments.models import Tournament


class InstitutionAdjRuleViewTestCase(TestCase):

    def test_registered_counts_handle_missing_type_and_ignore_other_tournaments(self):
        tournament = Tournament.objects.create(slug='current')
        other_tournament = Tournament.objects.create(slug='other')
        adj_only = Institution.objects.create(name='Adj Only', code='ADJ')
        team_only = Institution.objects.create(name='Team Only', code='TEAM')
        Adjudicator.objects.create(tournament=tournament, institution=adj_only, name='Current Adjudicator')
        Team.objects.create(tournament=other_tournament, institution=adj_only, reference='Other Team')
        Team.objects.create(tournament=tournament, institution=team_only, reference='Current Team')
        Adjudicator.objects.create(tournament=other_tournament, institution=team_only, name='Other Adjudicator')

        view = InstitutionAdjRuleView()
        view._tournament_from_url = tournament
        rows = {row[0]['text']: row[1]['text'] for row in view.get_table().jsondict()['data']}

        self.assertEqual(rows, {'ADJ': '0/1', 'TEAM': '1/0'})

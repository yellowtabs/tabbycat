from types import SimpleNamespace

from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.template.loader import render_to_string

from adjallocation.models import DebateAdjudicator
from adjfeedback.models import AdjudicatorFeedback
from adjfeedback.views import LatestFeedbackView
from draw.models import Debate, DebateTeam
from participants.models import Adjudicator, Team
from results.models import BallotSubmission, TeamScore, TeamScoreByAdj
from tournaments.models import Round, Tournament


class FeedbackCardResultTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(name='Feedback review', slug='feedback-review')
        round_ = Round.objects.create(tournament=self.tournament, seq=1, name='Round 1',
            abbreviation='R1', draw_type=Round.DrawType.MANUAL)
        debate = Debate.objects.create(round=round_)
        team = Team.objects.create(tournament=self.tournament, reference='Team A')
        self.debate_team = DebateTeam.objects.create(debate=debate, team=team, side=0)
        adjudicator = Adjudicator.objects.create(tournament=self.tournament, name='Judge A')
        self.debate_adj = DebateAdjudicator.objects.create(debate=debate, adjudicator=adjudicator,
            type=DebateAdjudicator.TYPE_CHAIR)
        self.ballot = BallotSubmission.objects.create(debate=debate, confirmed=True,
            submitter_type=BallotSubmission.Submitter.TABROOM)
        self.feedback = AdjudicatorFeedback.objects.create(adjudicator=adjudicator,
            source_team=self.debate_team, score=7, confirmed=True,
            submitter_type=AdjudicatorFeedback.Submitter.TABROOM)

    def feedbacks(self):
        view = LatestFeedbackView()
        view._tournament_from_url = self.tournament
        view.request = RequestFactory().get('/feedback/', {'show': 'all'})
        return view.get_feedbacks()

    def render_card(self, feedback):
        request = RequestFactory().get('/feedback/')
        return render_to_string('feedback_card.html', {
            'feedback': feedback,
            'tournament': self.tournament,
            'pref': SimpleNamespace(feedback_from_teams='all-adjs'),
            'score_thresholds': {'low_score': 0, 'medium_score': 1, 'high_score': 9},
        }, request=request)

    def test_two_team_result_and_dissenting_adjudicator_call(self):
        TeamScore.objects.create(ballot_submission=self.ballot, debate_team=self.debate_team,
            win=True, points=1)
        TeamScoreByAdj.objects.create(ballot_submission=self.ballot,
            debate_adjudicator=self.debate_adj, debate_team=self.debate_team, win=False)

        with CaptureQueriesContext(connection) as queries:
            feedback = self.feedbacks()[0]

        self.assertEqual(feedback.team_result_class, 'success')
        self.assertIs(feedback.adjudicator_team_win, False)
        self.assertEqual(sum('results_teamscorebyadj' in q['sql'] for q in queries), 1)
        card = self.render_card(feedback)
        self.assertIn('Won as', card)
        self.assertIn('Adj → Loss', card)

    def test_four_team_placement_uses_points_without_vote_query(self):
        self.tournament.preferences['debate_rules__teams_in_debate'] = 4
        TeamScore.objects.create(ballot_submission=self.ballot, debate_team=self.debate_team,
            points=2)

        with CaptureQueriesContext(connection) as queries:
            feedback = self.feedbacks()[0]

        self.assertEqual(feedback.source_team.get_result_display(), 'placed 2nd')
        self.assertEqual(feedback.team_result_class, 'primary')
        self.assertFalse(hasattr(feedback, 'adjudicator_team_win'))
        self.assertFalse(any('results_teamscorebyadj' in q['sql'] for q in queries))
        card = self.render_card(feedback)
        self.assertIn('Placed 2nd as', card)
        self.assertNotIn('Adj →', card)

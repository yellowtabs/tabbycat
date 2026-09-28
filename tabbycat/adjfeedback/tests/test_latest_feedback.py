from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime, timezone
import json

from django.test import RequestFactory, SimpleTestCase

from adjfeedback.views import FeedbackMixin, LatestFeedbackView


class FeedbackQueryset:
    def __init__(self, total):
        self.total = total
        self.filters = []
        self.order = None

    def count(self):
        return self.total

    def select_related(self, *fields):
        return self

    def order_by(self, *fields):
        self.order = fields
        return self

    def filter(self, condition=None, **kwargs):
        self.filters.append(condition if condition is not None else kwargs)
        return self

    def __getitem__(self, selection):
        return selection


class LatestFeedbackViewTests(SimpleTestCase):
    def make_view(self, params):
        view = LatestFeedbackView()
        view.request = RequestFactory().get('/', params)
        view._tournament_from_url = SimpleNamespace(pref=lambda name: {
            'adj_min_score': 0.0, 'adj_max_score': 10.0,
        }[name])
        return view

    def test_card_payload_contains_sort_and_group_metadata(self):
        feedback = SimpleNamespace(
            pk=9, round=SimpleNamespace(pk=2, name='Round 2', seq=2),
            debate=SimpleNamespace(venue=SimpleNamespace(pk=3, name='Auditorium')),
            adjudicator=SimpleNamespace(pk=4, name='Judge A'),
            source_team_id=5, source_team=SimpleNamespace(team=SimpleNamespace(pk=5, short_name='Team A')),
            source_adjudicator_id=None, score=7.5,
            timestamp=datetime(2026, 9, 26, tzinfo=timezone.utc),
        )
        view = LatestFeedbackView()
        view._tournament_from_url = SimpleNamespace()
        request = RequestFactory().get('/feedback/latest/', {'cards': '1', 'show': 'all'})
        view.request = request
        with patch.object(view, 'get_feedbacks', return_value=[feedback]), \
                patch.object(view, 'get_score_thresholds', return_value={}), \
                patch('adjfeedback.views.render_to_string', return_value='<div>Card</div>') as render:
            response = view.get(request)
        card = json.loads(response.content)['cards'][0]
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(card['round'], {'id': 2, 'name': 'Round 2', 'seq': 2})
        self.assertEqual(card['venue'], {'id': 3, 'label': 'Auditorium'})
        self.assertEqual(card['source'], {'id': ['team', 5], 'label': 'Team A'})
        self.assertEqual(card['score'], 7.5)
        self.assertEqual(render.call_args.kwargs['request'], request)
        self.assertEqual(render.call_args.args[1]['feedback_next_url'], request.path)

    def test_percentage_limits_and_all(self):
        for selection, expected in (
            ('25', 10), ('50', 20), ('75', 30), ('all', None),
        ):
            with self.subTest(selection=selection):
                queryset = FeedbackQueryset(40)
                view = self.make_view({'show': selection})
                with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
                    result = view.get_feedback_queryset()
                self.assertEqual(result, queryset if selection == 'all' else slice(None, expected))
                self.assertEqual(view.feedback_total, 40)

    def test_small_total_rounds_up_and_invalid_selection_defaults_to_25_percent(self):
        view = self.make_view({'show': 'invalid'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(1)):
            self.assertEqual(view.get_feedback_queryset(), slice(None, 1))
        self.assertEqual(view.feedback_portion, '25')

    def test_round_filter_and_score_order_apply_before_limit(self):
        queryset = FeedbackQueryset(40)
        view = self.make_view({
            'round': '5', 'order': 'score_desc', 'show': '50',
        })
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            result = view.get_feedback_queryset()
        self.assertEqual(result, slice(None, 20))
        self.assertEqual(len(queryset.filters), 1)
        self.assertEqual(queryset.order, ('-score', '-timestamp', '-pk'))

    def test_score_ticks_filter_before_percentage_limit(self):
        queryset = FeedbackQueryset(40)
        view = self.make_view({'score_min': '25', 'score_max': '75', 'show': '50'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            result = view.get_feedback_queryset()
        self.assertEqual(queryset.filters, [{'score__gte': 2.5, 'score__lte': 7.5}])
        self.assertEqual(result, slice(None, 20))

    def test_invalid_or_reversed_score_ticks(self):
        view = self.make_view({'score_min': '90', 'score_max': '10', 'show': 'all'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(0)):
            view.get_feedback_queryset()
        self.assertEqual(view.score_min_tick, 10)
        self.assertEqual(view.score_max_tick, 90)
        view = self.make_view({'score_min': 'NaN', 'score_max': '101', 'show': 'all'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(0)):
            view.get_feedback_queryset()
        self.assertEqual((view.score_min_tick, view.score_max_tick), (0, 100))

    def test_score_filter_keeps_unrestricted_end_open(self):
        queryset = FeedbackQueryset(10)
        view = self.make_view({'score_max': '50', 'show': 'all'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            view.get_feedback_queryset()
        self.assertEqual(queryset.filters, [{'score__lte': 5.0}])

    def test_grouping_keeps_order_and_source_types_separate(self):
        venue = SimpleNamespace(pk=1, name='Auditorium')
        old_round = SimpleNamespace(pk=1, name='Round 1', seq=1)
        new_round = SimpleNamespace(pk=2, name='Round 2', seq=2)
        team = SimpleNamespace(pk=2, short_name='Team A')
        adjudicator = SimpleNamespace(pk=2, name='Judge A')
        feedbacks = [
            SimpleNamespace(round=old_round, debate=SimpleNamespace(venue=venue), source_team_id=2,
                source_team=SimpleNamespace(team=team), source_adjudicator_id=None),
            SimpleNamespace(round=old_round, debate=SimpleNamespace(venue=venue), source_team_id=None,
                source_adjudicator_id=2,
                source_adjudicator=SimpleNamespace(adjudicator=adjudicator)),
            SimpleNamespace(round=new_round, debate=SimpleNamespace(venue=venue), source_team_id=2,
                source_team=SimpleNamespace(team=team), source_adjudicator_id=None),
        ]
        view = LatestFeedbackView()
        view.primary_group = 'venue'
        view.secondary_group = 'source'
        view.feedback_order = 'newest'
        groups = view.group_feedbacks(feedbacks)
        self.assertEqual([g['label'] for g in groups], ['Round 2', 'Round 1'])
        self.assertEqual([g['primary'][0]['label'] for g in groups], ['Auditorium', 'Auditorium'])
        self.assertEqual([g['label'] for g in groups[1]['primary'][0]['secondary']],
            ['Team A', 'Judge A'])

        view.feedback_order = 'oldest'
        self.assertEqual([g['label'] for g in view.group_feedbacks(feedbacks)],
            ['Round 1', 'Round 2'])

        view.feedback_order = 'score_desc'
        self.assertEqual([g['label'] for g in view.group_feedbacks(feedbacks)],
            ['Round 1', 'Round 2'])

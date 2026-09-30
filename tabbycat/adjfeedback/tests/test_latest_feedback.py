import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from adjfeedback.models import AdjudicatorFeedback
from adjfeedback.views import ConfirmFeedbackView, FeedbackMixin, IgnoreFeedbackView, LatestFeedbackView


class FeedbackQueryset:
    def __init__(self, total, filtered_total=None):
        self.total = total
        self.filtered_total = filtered_total
        self.filters = []
        self.order = None

    def count(self):
        return self.filtered_total if self.filters and self.filtered_total is not None else self.total

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
            'adj_min_score': 0.0, 'adj_max_score': 10.0, 'adj_score_step': 0.5,
        }[name])
        return view

    def test_card_payload_contains_sort_and_group_metadata(self):
        feedback = SimpleNamespace(
            pk=9, round=SimpleNamespace(pk=2, name='Round 2', seq=2),
            debate=SimpleNamespace(venue=SimpleNamespace(pk=3, name='Auditorium')),
            adjudicator_id=4, adjudicator=SimpleNamespace(pk=4, name='Judge A'),
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
        self.assertEqual(card['duplicate_key'], [4, 5, None])
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
                self.assertIs(result, queryset)
                self.assertEqual(view.feedback_total, 40)

    def test_invalid_selection_defaults_to_all_feedback(self):
        view = self.make_view({'show': 'invalid'})
        queryset = FeedbackQueryset(1)
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            self.assertIs(view.get_feedback_queryset(), queryset)
        self.assertEqual(view.feedback_portion, 'all')

        view = self.make_view({})
        queryset = FeedbackQueryset(40)
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            self.assertIs(view.get_feedback_queryset(), queryset)
        self.assertEqual(view.feedback_portion, 'all')

    def test_round_filter_and_score_order_apply_before_limit(self):
        queryset = FeedbackQueryset(40)
        view = self.make_view({
            'round': '5', 'order': 'score_desc', 'show': '50',
        })
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            result = view.get_feedback_queryset()
        self.assertIs(result, queryset)
        self.assertEqual(len(queryset.filters), 1)
        self.assertEqual(queryset.order, ('-score', '-timestamp', '-pk'))

    def test_score_filter_shows_all_matches_without_changing_global_count(self):
        queryset = FeedbackQueryset(40, filtered_total=3)
        view = self.make_view({'score_min': '5', 'score_max': '15', 'show': '50'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            result = view.get_feedback_queryset()
        self.assertEqual(queryset.filters, [{'score__gte': 2.5, 'score__lte': 7.5}])
        self.assertIs(result, queryset)
        self.assertEqual(view.feedback_total, 40)

    def test_round_filter_keeps_global_percentage_limit(self):
        queryset = FeedbackQueryset(40, filtered_total=5)
        view = self.make_view({'round': '5', 'show': '50'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            self.assertIs(view.get_feedback_queryset(), queryset)
        self.assertEqual(view.feedback_total, 40)

    def test_duplicate_versions_stay_together_and_cross_percentage_cutoff(self):
        def feedback(pk, version, source, target=1):
            return SimpleNamespace(pk=pk, version=version, adjudicator_id=target,
                source_team_id=source, source_adjudicator_id=None)

        view = self.make_view({'show': '25'})
        view.get_options()
        view.feedback_total = 8
        items = [feedback(4, 1, 4), feedback(3, 2, 3), feedback(2, 1, 3),
                 feedback(1, 1, 1)]
        with patch.object(FeedbackMixin, 'get_feedbacks', return_value=items):
            result = view.get_feedbacks()
        self.assertEqual([item.pk for item in result], [4, 3, 2])
        self.assertEqual([(item.duplicate_number, item.duplicate_total) for item in result[1:]],
            [(2, 2), (1, 2)])

    def test_duplicate_key_keeps_sources_and_targets_separate(self):
        team = SimpleNamespace(adjudicator_id=1, source_team_id=7, source_adjudicator_id=None)
        adjudicator = SimpleNamespace(adjudicator_id=1, source_team_id=None, source_adjudicator_id=7)
        other_target = SimpleNamespace(adjudicator_id=2, source_team_id=7, source_adjudicator_id=None)
        self.assertEqual(len({LatestFeedbackView.duplicate_key(item)
                              for item in (team, adjudicator, other_target)}), 3)

    def test_invalid_or_reversed_score_ticks(self):
        view = self.make_view({'score_min': '18', 'score_max': '2', 'show': 'all'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(0)):
            view.get_feedback_queryset()
        self.assertEqual(view.score_min_tick, 2)
        self.assertEqual(view.score_max_tick, 18)
        view = self.make_view({'score_min': 'NaN', 'score_max': '21', 'show': 'all'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(0)):
            view.get_feedback_queryset()
        self.assertEqual((view.score_min_tick, view.score_max_tick), (0, 20))

    def test_score_filter_keeps_unrestricted_end_open(self):
        queryset = FeedbackQueryset(10)
        view = self.make_view({'score_max': '10', 'show': 'all'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
            view.get_feedback_queryset()
        self.assertEqual(queryset.filters, [{'score__lte': 5.0}])

    def test_final_tick_reaches_maximum_when_step_does_not_divide_range(self):
        view = self.make_view({'show': 'all'})
        view._tournament_from_url.pref = lambda name: {
            'adj_min_score': 2.0, 'adj_max_score': 9.8, 'adj_score_step': 0.5,
        }[name]
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(0)):
            view.get_feedback_queryset()
        self.assertEqual(view.score_tick_count, 16)
        self.assertEqual(view.score_for_tick(15), 9.5)
        self.assertEqual(view.score_for_tick(16), 9.8)

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


class FeedbackToggleResponseTests(SimpleTestCase):
    def make_feedback(self):
        feedback = SimpleNamespace(
            pk=1, confirmed=False, ignored=False,
            source_adjudicator=None,
            source_team=SimpleNamespace(team=SimpleNamespace(short_name='Team A')),
            adjudicator=SimpleNamespace(get_public_name=lambda tournament: 'Judge A'),
            save=Mock(),
            _unique_unconfirm_args=lambda: {'source_team_id': 7},
        )
        return feedback

    def test_confirm_json_updates_auto_unconfirmed_feedback(self):
        request = RequestFactory().post('/', HTTP_ACCEPT='application/json')
        request.user = SimpleNamespace()
        view = ConfirmFeedbackView()
        view.request = request
        view._tournament_from_url = SimpleNamespace(id=1)
        feedback = self.make_feedback()
        with patch.object(AdjudicatorFeedback.objects, 'annotate') as annotated, \
                patch.object(AdjudicatorFeedback.objects, 'filter') as filtered:
            annotated.return_value.get.return_value = feedback
            filtered.return_value.values_list.return_value = [
                (1, True, False), (2, False, False),
            ]
            response = view.post(request, feedback_id=1)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in payload['updates']], [1, 2])
        self.assertEqual(payload['updates'][0]['confirm_label'], 'Discard')
        self.assertIn('Discarded;', payload['updates'][1]['status_html'])
        feedback.save.assert_called_once()

    def test_ignore_json_returns_only_changed_feedback(self):
        request = RequestFactory().post('/', HTTP_ACCEPT='application/json')
        view = IgnoreFeedbackView()
        view.request = request
        view._tournament_from_url = SimpleNamespace(id=1)
        feedback = self.make_feedback()
        with patch.object(AdjudicatorFeedback.objects, 'annotate') as annotated, \
                patch.object(AdjudicatorFeedback.objects, 'filter') as filtered:
            annotated.return_value.get.return_value = feedback
            response = view.post(request, feedback_id=1)
        payload = json.loads(response.content)
        self.assertEqual(len(payload['updates']), 1)
        self.assertEqual(payload['updates'][0]['ignore_label'], 'Include')
        self.assertIn('Ignored;', payload['updates'][0]['status_html'])
        filtered.assert_not_called()

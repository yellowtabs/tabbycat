from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from adjfeedback.views import FeedbackMixin, LatestFeedbackView


class FeedbackQueryset:
    def __init__(self, total):
        self.total = total

    def count(self):
        return self.total

    def order_by(self, *fields):
        return self

    def __getitem__(self, selection):
        return selection


class LatestFeedbackViewTests(SimpleTestCase):
    def test_percentage_limits_and_all(self):
        for selection, expected in (
            ('25', 10), ('50', 20), ('75', 30), ('all', None),
        ):
            with self.subTest(selection=selection):
                queryset = FeedbackQueryset(40)
                view = LatestFeedbackView()
                view.request = RequestFactory().get('/', {'show': selection})
                with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=queryset):
                    result = view.get_feedback_queryset()
                self.assertEqual(result, queryset if selection == 'all' else slice(None, expected))
                self.assertEqual(view.feedback_total, 40)

    def test_small_total_rounds_up_and_invalid_selection_defaults_to_25_percent(self):
        view = LatestFeedbackView()
        view.request = RequestFactory().get('/', {'show': 'invalid'})
        with patch.object(FeedbackMixin, 'get_feedback_queryset', return_value=FeedbackQueryset(1)):
            self.assertEqual(view.get_feedback_queryset(), slice(None, 1))
        self.assertEqual(view.feedback_portion, '25')

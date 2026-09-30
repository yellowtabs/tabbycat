from django.contrib.auth import get_user_model
from django.test import TestCase

from actionlog.models import ActionLogEntry
from participants.models import Adjudicator
from tournaments.models import Round, Tournament
from utils.misc import reverse_tournament


class AdjudicatorStatusSaveTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(name='Status saves', slug='status-saves')
        self.tournament.current_round = Round.objects.create(tournament=self.tournament, seq=1,
            name='Round 1', abbreviation='R1', draw_type=Round.DrawType.MANUAL)
        self.tournament.save()
        self.adjudicator = Adjudicator.objects.create(tournament=self.tournament, name='Judge')
        self.client.force_login(get_user_model().objects.create_superuser('status-admin', password='test'))

    def test_tester_and_breaking_status_can_be_enabled_and_disabled(self):
        for field, model_field, route, action in [
            ('tester', 'is_tester', 'adjfeedback-set-adj-tester-status',
                ActionLogEntry.ActionType.ADJUDICATOR_TESTER_SET),
            ('breaking', 'breaking', 'adjfeedback-set-adj-breaking-status',
                ActionLogEntry.ActionType.ADJUDICATOR_BREAK_SET),
        ]:
            for value in [True, False]:
                with self.subTest(field=field, value=value):
                    response = self.client.post(reverse_tournament(route, self.tournament),
                        {'id': self.adjudicator.pk, field: value}, content_type='application/json')
                    self.assertEqual(response.status_code, 200)
                    self.adjudicator.refresh_from_db()
                    self.assertEqual(getattr(self.adjudicator, model_field), value)
                    self.assertEqual(ActionLogEntry.objects.order_by('-id').first().type, action)

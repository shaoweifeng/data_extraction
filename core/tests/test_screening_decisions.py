"""Final screening decision rules independent of the persistence adapter."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from core.screening.services.decision_service import ScreeningDecisionService


class ScreeningDecisionServiceTests(SimpleTestCase):
    def test_manual_decision_wins(self):
        result = {'decision': 'included', 'consensus': 'included'}
        self.assertEqual(
            ScreeningDecisionService.resolve(
                result, SimpleNamespace(decision='excluded'),
            ),
            'excluded',
        )

    def test_database_decisions_and_conflicts_are_preserved(self):
        self.assertEqual(
            ScreeningDecisionService.resolve(
                {'decision': 'excluded', 'consensus': 'excluded'}, None,
            ),
            'excluded',
        )
        self.assertEqual(
            ScreeningDecisionService.resolve(
                {'decision': 'uncertain', 'consensus': 'conflict'}, None,
            ),
            'conflict',
        )

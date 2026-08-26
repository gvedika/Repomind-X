from app.services.evaluation import EvaluationMetrics


def test_repository_understanding_score():
    assert EvaluationMetrics(1, 1, 1, 1).rus == 1.0
    assert EvaluationMetrics(.8, .6, .9, .7).rus == .74

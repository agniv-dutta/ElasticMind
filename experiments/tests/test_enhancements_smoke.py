"""Smoke tests for enhancement stubs/behavior."""
def test_conformal_import():
    import ml.conformal.conformal as m
    assert hasattr(m, "apply_intervals")


def test_optuna_module():
    import ml.tune.optuna_tune as m
    assert hasattr(m, "tune")
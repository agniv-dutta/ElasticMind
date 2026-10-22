from backend.app.metrics.calculator import (
    calculate_metrics, cost_usd, energy_kwh_estimated, latency_ms, sla_violations, utilization,
)


def test_utilization_zero_full_and_mid_scale_up():
    assert utilization(0, 2, 100) == 0
    assert utilization(200, 2, 100) == 1
    assert utilization(150, 2, 100) == 0.75


def test_sla_and_latency_hand_calculated():
    assert sla_violations(100, 100, 200, 200) == 0
    assert sla_violations(101, 100, 100, 200) == 1
    assert latency_ms(0, 1, 100) == 1


def test_replica_seconds_bill_starting_and_draining_replicas():
    assert cost_usd(3 * 30, 0.01 / 3600) == 0.00025


def test_energy_hand_calculated_zero_full_and_mid_scale_up():
    assert energy_kwh_estimated(0, 2, 60, 10, 100) == 2 * 10 * 60 / 3_600_000
    assert energy_kwh_estimated(1, 2, 60, 10, 100) == 2 * 100 * 60 / 3_600_000
    assert energy_kwh_estimated(0.5, 3, 60, 10, 100) == 3 * 55 * 60 / 3_600_000


def test_combined_calculator_uses_measured_latency_when_supplied():
    result = calculate_metrics(
        demand=10, served_load=10, running_replicas=1, capacity_per_replica=100,
        service_rate=100, latency_sla_ms=200, billed_replica_seconds=60,
        price_per_second=0.01 / 3600, dt_seconds=60, idle_w=10, peak_w=100,
        measured_latency_ms=250,
    )
    assert result.utilization == 0.1
    assert result.latency_ms == 250
    assert result.sla_violations == 1
    assert abs(result.cost_usd - (0.01 / 60)) < 1e-12

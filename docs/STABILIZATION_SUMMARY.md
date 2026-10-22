# Stabilization Summary

## What was implemented
- Python 3.11 pinned everywhere (.python-version, all pyproject requires-python >=3.11,<3.13), Dockerfiles use python:3.11-slim with libgomp1 for LightGBM images; target_app/loadgen kept slim.
- CapacityActuator interface with set_desired/get_state(), LocalReplicaPool with STARTING->RUNNING (STARTUP_DELAY_S) and RUNNING->DRAINING->STOPPED (DRAIN_DELAY_S), cooldown/min/max, MockEcsActuator with fake boto3-style client, shared contract tests, AwsEcsActuator stubbed with TODOs; ACTUATOR defaults to local.
- experiments/calibrate_capacity.py ramps load against one replica, finds p95 crossing SLA, writes CAPACITY_PER_REPLICA_RPM (+20% margin) to configs/calibration.yaml and latency-vs-load chart; Settings/AutoscalerConfig load it; documented re-run on AWS.
- Dashboard shows replica states, forecast band with horizon shift, decision-source badges, measured/simulated/estimated badges, model version, banner (profile/TIME_SCALE/ACTUATOR), controls (policy/start-stop/bias/spike), no direct capacity edits.
- experiments/run_live.py runs policies (static/reactive/ML-predictive/ML+safeguards), 3 repeats, misprediction scenarios with/without safeguards, writes CSVs/charts/summary, fails on acceptance criteria; make demo added.
- Stabilization checklist + acceptance tests added.

## Still not fully implemented / gaps
- Model artifacts may not exist in all environments (backend fails gracefully if missing); need training or S3.
- Docker daemon/Terraform not available locally for full integration.
- Some live metrics remain placeholders in places; simulator is authoritative.
- experiments/run_live uses simulator internally for reproducibility; true end-to-end against live stack needs the backend running.
- AwsEcsActuator is stubbed (TODOs).
- Full make doctor in clean environments needs dependencies installed.
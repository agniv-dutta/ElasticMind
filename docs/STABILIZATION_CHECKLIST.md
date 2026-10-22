# Stabilization Checklist

- [ ] make doctor passes on Python 3.11, in Docker and locally
- [ ] the model loads in the backend container; /config shows the model version
- [ ] every tick in SQLite has a decision_source and a reason
- [ ] in the ML run, the majority of scale-ups happen before the observed spike (lead time > 0) and the safety net fires rarely
- [ ] running replicas lag desired by about STARTUP_DELAY_S
- [ ] cost and energy tests match the hand-calculated values
- [ ] ML-predictive beats reactive on SLA violation minutes for the local_demo profile (if not, report honestly and list tuning options)
- [ ] the actuator contract suite passes for LocalReplicaPool and MockEcsActuator
- [ ] under-predict -50%: the safeguards cut SLA violations vs without them
- [ ] make demo runs end to end with no manual steps
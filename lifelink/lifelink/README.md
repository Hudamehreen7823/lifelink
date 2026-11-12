# LifeLink

A fairness-aware resource redistribution platform: providers list surplus (food, books, clothes, household items), recipients request what they need, and LifeLink ranks recipients with a transparent multi-criteria score, reserves quantity transactionally, tracks pickup and delivery by volunteers, and reports impact from **confirmed** deliveries only.

## Run it

```bash
pip install -r requirements.txt
python -m app.seed            # demo data (add --reset to start over)
python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000 (app) or http://localhost:8000/docs (Swagger UI).
Demo logins, all with password `demo1234`: `admin@`, `provider1@`, `provider2@`, `asha@`, `seva@`, `bright@`, `ravi@` (volunteer), all at `lifelink.test`.

```bash
python -m pytest -q                              # 41 tests
python -m experiments.run_experiment --seeds 50  # regenerates results/ (about 30 s)
```

## What is implemented (blueprint to code)

| Blueprint item | Where |
|---|---|
| Provider, recipient, volunteer, admin accounts; JWT + role checks; admin verification | `app/main.py`, `app/security.py` |
| Listings, quantity management, requests | `app/services.py` |
| Weighted scoring S = 0.20 D + 0.25 U + 0.25 N + 0.20 C + 0.10 T, hard eligibility filters | `app/matching.py` |
| Fairness term (recent share of demand received; urgent requests exempt) | `app/matching.py` |
| Baselines: nearest-first, oldest-request-first | `app/matching.py` |
| Transactional reservation, CHECK constraints, reject/expiry release and re-offer | `app/services.py`, `app/db.py` |
| Volunteer assignment, pickup/delivery state machine, recipient confirmation | `app/services.py` |
| Audit log, in-app notifications, optional SMTP email | `app/services.py`, `app/notifier.py` |
| Impact metrics, Jain fairness index | `GET /api/v1/analytics/impact` |
| Experiment: 4 strategies, 6 scenarios, weight and lambda sensitivity | `experiments/`, `results/` |
| Maps (Leaflet/OpenStreetMap), geocoding (Nominatim) | `static/app.js` (need internet) |

Deliberate departures from the blueprint's suggested stack: Python/FastAPI and SQLite instead of Java/Spring Boot and PostgreSQL, because the build environment could not reach Maven Central. The schema, REST surface, algorithm and workflow are stack-independent; see "Porting to Spring Boot" below.

## Honest limits

* Evaluation results are **simulated** on synthetic data with stated assumptions (`results/results.md`). They are not evidence of real-world waste reduction; run a pilot to get that.
* In the simulation, LifeLink's gains are in urgent-need fulfilment and fairness. Redistribution rate and deadline success are statistically about the same as the baselines, and LifeLink delivers over longer distances than nearest-first (about 4.6 km more on average in the headline scenario).
* Weights (20/25/25/20/10) and lambda (0.2) are starting hypotheses; the sensitivity tables show the trade-offs.
* Medicines are out of scope. Email needs `LIFELINK_SMTP_HOST` (and related variables); without it, notifications are in-app only.
* Demo accounts and the SQLite file are for development. Set `LIFELINK_SECRET` and delete the demo users before any real deployment.

## Porting to Spring Boot

Entities map one-to-one to the tables in `app/db.py`; `app/matching.py` is pure functions (about 150 lines) that translate directly into a `MatchingService`; the reservation `UPDATE ... WHERE quantity_available >= ?` becomes a JPA `@Modifying` query inside `@Transactional`.

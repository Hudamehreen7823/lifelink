from datetime import datetime, timedelta, timezone

import pytest

from app import matching
from app.matching import Candidate, Listing

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
# Centre point plus offsets: 0.01 deg latitude ~ 1.11 km
LAT, LON = 16.50, 80.65


def listing(**kw):
    base = dict(id=1, category="food", condition="good", quantity_available=100,
                deadline=NOW + timedelta(hours=24), lat=LAT, lon=LON)
    base.update(kw)
    return Listing(**base)


def cand(rid, km=5.0, **kw):
    base = dict(request_id=rid, recipient_id=rid, org_id=rid, org_name=f"Org{rid}", org_type="food_bank",
                lat=LAT + km / 111.0, lon=LON, category="food", quantity_needed=100, remaining_need=100, urgency=3,
                min_condition="any", created_at=NOW - timedelta(days=rid), capacity_remaining=1000,
                requested_30d=100, received_30d=0, verified=True)
    base.update(kw)
    return Candidate(**base)


def test_haversine_known_distance():
    # Vijayawada -> Guntur is ~ 31 km as the crow flies
    d = matching.haversine_km(16.5062, 80.6480, 16.3067, 80.4365)
    assert 28 < d < 34


@pytest.mark.parametrize("kw,reason", [
    (dict(verified=False), "not verified"),
    (dict(category="books"), "category"),
    (dict(remaining_need=0), "fully covered"),
    (dict(capacity_remaining=0), "capacity"),
    (dict(km=80), "service radius"),
    (dict(min_condition="new"), "condition"),
])
def test_hard_filters_exclude(kw, reason):
    ranked, excluded = matching.rank_candidates(listing(), [cand(1, **kw)], NOW)
    assert ranked == []
    assert reason in excluded[0].reason


def test_cannot_collect_before_deadline_is_excluded():
    l = listing(deadline=NOW + timedelta(hours=1, minutes=30))  # 1h prep + travel 5km/25kmh=0.2h fits; 40km does not
    near, far = cand(1, km=5), cand(2, km=40)
    ranked, excluded = matching.rank_candidates(l, [near, far], NOW)
    assert [r.request_id for r in ranked] == [1]
    assert "deadline" in excluded[0].reason


def test_score_components_are_normalised_0_100():
    ranked, _ = matching.rank_candidates(listing(), [cand(1), cand(2, km=45, urgency=1, remaining_need=1)], NOW)
    for r in ranked:
        for name, v in r.components.items():
            assert 0 <= v <= 100, (name, v)
        assert 0 <= r.score_weighted <= 100


def test_weighted_score_matches_formula():
    r = matching.rank_candidates(listing(), [cand(1, km=10, urgency=4, remaining_need=50)], NOW)[0][0]
    c, w = r.components, matching.DEFAULT_WEIGHTS
    expected = (w["proximity"] * c["proximity"] + w["urgency"] * c["urgency"] + w["unmet_need"] * c["unmet_need"]
                + w["compatibility"] * c["compatibility"] + w["deadline"] * c["deadline"])
    assert r.score_weighted == pytest.approx(expected, abs=1e-2)
    assert c["urgency"] == 80 and c["unmet_need"] == 50


def test_nearest_vs_lifelink_disagree_on_urgent_need():
    near_low = cand(1, km=2, urgency=1, remaining_need=20)
    far_urgent = cand(2, km=20, urgency=5, remaining_need=100)
    nearest, _ = matching.rank_candidates(listing(), [near_low, far_urgent], NOW, "nearest")
    smart, _ = matching.rank_candidates(listing(), [near_low, far_urgent], NOW, "lifelink")
    assert nearest[0].request_id == 1
    assert smart[0].request_id == 2


def test_chronological_orders_by_request_age():
    cs = [cand(1, created_at=NOW - timedelta(hours=1)), cand(2, created_at=NOW - timedelta(days=3)),
          cand(3, created_at=NOW - timedelta(days=1))]
    ranked, _ = matching.rank_candidates(listing(), cs, NOW, "chronological")
    assert [r.request_id for r in ranked] == [2, 3, 1]


def test_fairness_demotes_recent_heavy_recipient():
    hog = cand(1, km=2, received_30d=300, requested_30d=320)
    fresh = cand(2, km=3, received_30d=0, requested_30d=100)
    plain, _ = matching.rank_candidates(listing(), [hog, fresh], NOW, "lifelink")
    fair, _ = matching.rank_candidates(listing(), [hog, fresh], NOW, "lifelink_fair")
    assert plain[0].request_id == 1            # closer wins without fairness
    assert fair[0].request_id == 2             # history now tips it
    assert fair[1].components["fairness"] < 10


def test_urgent_requests_are_never_penalised_by_history():
    urgent = cand(1, urgency=5, received_30d=500, requested_30d=500)
    r = matching.rank_candidates(listing(), [urgent], NOW)[0][0]
    assert r.components["fairness"] == 100


def test_fairness_never_overrides_eligibility():
    # a perfect-fairness recipient that is out of radius stays excluded
    ranked, excluded = matching.rank_candidates(listing(), [cand(1, km=90, received_30d=0)], NOW)
    assert ranked == [] and excluded


def test_with_ranks_reports_all_strategies():
    ranked, _ = matching.rank_candidates(listing(), [cand(1, km=2), cand(2, km=9, urgency=5)], NOW, with_ranks=True)
    assert set(ranked[0].ranks) == set(matching.STRATEGIES)


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError):
        matching.rank_candidates(listing(), [cand(1)], NOW, "magic")

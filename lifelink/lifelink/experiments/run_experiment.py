"""Run the full evaluation.   python -m experiments.run_experiment [--seeds 50]

Writes results/results.json, results/results.md and results/*.png.
All scenarios are reported; nothing is cherry-picked. The 'headline' scenario
(central hubs, supply = 0.5 x demand) was fixed in advance because scarcity is
where allocation fairness matters; it is shown first but not selected on results.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

from app import matching
from experiments.simulate import ASSUMPTIONS, SimConfig, run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")

STRATEGIES = ["chronological", "nearest", "lifelink", "lifelink_fair"]
LABELS = {"chronological": "Oldest request first", "nearest": "Nearest first",
          "lifelink": "LifeLink (weighted)", "lifelink_fair": "LifeLink + fairness"}
COLORS = {"chronological": "#2a78d6", "nearest": "#eb6834", "lifelink": "#1baf7a", "lifelink_fair": "#eda100"}

# key -> (label, higher_is_better, decimals)
METRICS = {
    "redistribution_rate": ("Redistribution rate (% of listed qty delivered)", True, 1),
    "deadline_success": ("Deadline success (% of accepted qty delivered in time)", True, 1),
    "unclaimed_rate": ("Unclaimed (% of listed qty never allocated)", False, 1),
    "late_loss_rate": ("Lost to missed deadline (% of listed qty)", False, 1),
    "hours_to_acceptance": ("Time to acceptance (hours)", False, 2),
    "demand_fulfilment": ("Demand fulfilment (% of requested qty delivered)", True, 1),
    "urgent_fulfilment": ("Urgent need fulfilment (urgency 4-5, %)", True, 1),
    "jain_fairness": ("Jain fairness index of fulfilment ratios (1 = equal)", True, 3),
    "need_share_deviation": ("Allocation vs need share deviation (0 = proportional)", False, 3),
    "hub_share_gap_abs": ("Hub over/under-allocation vs their share of need (pts)", False, 1),
    "mean_distance_km": ("Mean delivery distance (km)", False, 1),
}
CORE = ["redistribution_rate", "deadline_success", "urgent_fulfilment", "jain_fairness",
        "need_share_deviation", "hub_share_gap_abs", "hours_to_acceptance", "mean_distance_km"]

WEIGHT_SETS = {
    "default (20/25/25/20/10)": None,
    "equal (20 each)": dict(proximity=.2, urgency=.2, unmet_need=.2, compatibility=.2, deadline=.2),
    "proximity-heavy": dict(proximity=.5, urgency=.15, unmet_need=.15, compatibility=.1, deadline=.1),
    "urgency-heavy": dict(proximity=.1, urgency=.5, unmet_need=.15, compatibility=.15, deadline=.1),
    "need-heavy": dict(proximity=.1, urgency=.15, unmet_need=.5, compatibility=.15, deadline=.1),
    "no proximity": dict(proximity=0, urgency=.3, unmet_need=.3, compatibility=.25, deadline=.15),
}
LAMBDAS = [0.0, 0.1, 0.2, 0.4, 0.6, 0.8]


def stats_of(values):
    v = [x for x in values if not (isinstance(x, float) and math.isnan(x))]
    if not v:
        return {"mean": None, "sd": None, "ci95": None, "n": 0}
    sd = statistics.stdev(v) if len(v) > 1 else 0.0
    return {"mean": statistics.fmean(v), "sd": sd, "ci95": 1.96 * sd / math.sqrt(len(v)), "n": len(v)}


def collect(cfg_kwargs, seeds, strategy, weights=None, lam=matching.FAIRNESS_LAMBDA):
    runs = []
    for s in range(seeds):
        m = run(SimConfig(seed=s, **cfg_kwargs), strategy, weights, lam)
        m["hub_share_gap_abs"] = abs(m["hub_share_gap"])
        runs.append(m)
    return runs


def summarise(runs):
    return {k: stats_of([r[k] for r in runs]) for k in METRICS}


def paired(a_runs, b_runs):
    """LifeLink-fair minus baseline, per seed, with win counts in the 'better' direction."""
    out = {}
    for k, (_, hib, _) in METRICS.items():
        diffs, wins, ties = [], 0, 0
        for a, b in zip(a_runs, b_runs):
            if math.isnan(a[k]) or math.isnan(b[k]):
                continue
            d = a[k] - b[k]
            diffs.append(d)
            if abs(d) < 1e-9:
                ties += 1
            elif (d > 0) == hib:
                wins += 1
        st = stats_of(diffs)
        st.update(wins=wins, ties=ties)
        out[k] = st
    return out


def fmt(st, dec):
    if st["mean"] is None:
        return "n/a"
    return f"{st['mean']:.{dec}f} ± {st['ci95']:.{dec}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()

    scenarios = []
    for geo in ("central_hubs", "uniform"):
        for ratio in (0.5, 1.0, 1.5):
            cfg = dict(geography=geo, supply_ratio=ratio)
            runs = {s: collect(cfg, args.seeds, s) for s in STRATEGIES}
            scenarios.append({
                "id": f"{geo}_supply{ratio}", "geography": geo, "supply_ratio": ratio,
                "strategies": {s: summarise(runs[s]) for s in STRATEGIES},
                "paired_vs_nearest": paired(runs["lifelink_fair"], runs["nearest"]),
                "paired_vs_chronological": paired(runs["lifelink_fair"], runs["chronological"]),
                "paired_vs_weighted": paired(runs["lifelink_fair"], runs["lifelink"]),
            })
            print(f"  scenario {geo} supply={ratio} done", file=sys.stderr)

    head = dict(geography="central_hubs", supply_ratio=0.5)
    weight_rows = []
    for name, w in WEIGHT_SETS.items():
        weight_rows.append({"name": name, "weights": w or matching.DEFAULT_WEIGHTS,
                            "metrics": summarise(collect(head, args.seeds, "lifelink_fair", w))})
    lambda_rows = [{"lambda": lam, "metrics": summarise(collect(head, args.seeds, "lifelink_fair", None, lam))}
                   for lam in LAMBDAS]

    result = {
        "meta": {"seeds_per_scenario": args.seeds, "recipients": 40, "listings_per_run": 160, "days": 21,
                 "headline_scenario": "central_hubs_supply0.5", "simulated": True,
                 "default_weights": matching.DEFAULT_WEIGHTS, "fairness_lambda": matching.FAIRNESS_LAMBDA,
                 "runtime_seconds": round(time.time() - t0, 1), "assumptions": ASSUMPTIONS,
                 "note": "Synthetic data. These are simulation results, not measurements of real-world waste reduction."},
        "strategies": STRATEGIES, "labels": LABELS, "metrics": {k: {"label": v[0], "higher_is_better": v[1]}
                                                                for k, v in METRICS.items()},
        "scenarios": scenarios, "weight_sensitivity": weight_rows, "lambda_sensitivity": lambda_rows,
    }
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(result, fh, indent=1)
    write_markdown(result)
    if not args.no_plots:
        plots(result)
    print(f"Done in {time.time() - t0:.1f}s -> {OUT}", file=sys.stderr)


def write_markdown(res):
    n = res["meta"]["seeds_per_scenario"]
    L = [f"# LifeLink evaluation (simulated)\n",
         f"{n} random seeds per scenario; values are mean ± 95% CI. All data is synthetic - see the assumptions at the end.\n"]
    for sc in res["scenarios"]:
        star = " (headline)" if sc["id"] == res["meta"]["headline_scenario"] else ""
        L.append(f"\n## {sc['geography']}, supply = {sc['supply_ratio']} × demand{star}\n")
        L.append("| Metric | " + " | ".join(LABELS[s] for s in STRATEGIES) + " |")
        L.append("|---|" + "---|" * len(STRATEGIES))
        for k in CORE:
            lab, hib, dec = METRICS[k]
            L.append(f"| {lab} {'↑' if hib else '↓'} | " + " | ".join(fmt(sc["strategies"][s][k], dec) for s in STRATEGIES) + " |")
        L.append("\nPaired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):\n")
        L.append("| Metric | Mean diff ± 95% CI | Wins / seeds |")
        L.append("|---|---|---|")
        for k in CORE:
            lab, hib, dec = METRICS[k]
            p = sc["paired_vs_nearest"][k]
            L.append(f"| {lab} | {fmt(p, dec)} | {p['wins']}/{p['n']} |")
    L.append("\n## Weight sensitivity (headline scenario, LifeLink + fairness)\n")
    keys = ["redistribution_rate", "urgent_fulfilment", "jain_fairness", "need_share_deviation", "mean_distance_km"]
    L.append("| Weights | " + " | ".join(METRICS[k][0].split(" (")[0] for k in keys) + " |")
    L.append("|---|" + "---|" * len(keys))
    for row in res["weight_sensitivity"]:
        L.append(f"| {row['name']} | " + " | ".join(fmt(row["metrics"][k], METRICS[k][2]) for k in keys) + " |")
    L.append("\n## Fairness strength λ (headline scenario)\n")
    L.append("| λ | " + " | ".join(METRICS[k][0].split(" (")[0] for k in keys) + " |")
    L.append("|---|" + "---|" * len(keys))
    for row in res["lambda_sensitivity"]:
        L.append(f"| {row['lambda']} | " + " | ".join(fmt(row["metrics"][k], METRICS[k][2]) for k in keys) + " |")
    L.append("\n## Assumptions\n")
    L += [f"- {a}" for a in res["meta"]["assumptions"]]
    L.append(f"\n{res['meta']['note']}\n")
    with open(os.path.join(OUT, "results.md"), "w") as fh:
        fh.write("\n".join(L))


def plots(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#a8a79f", "axes.labelcolor": "#52514e", "xtick.color": "#52514e",
                         "ytick.color": "#52514e", "axes.titlecolor": "#0b0b0b", "figure.facecolor": "#fcfcfb",
                         "axes.facecolor": "#fcfcfb"})

    def bars(ax, sc, key, scale=1.0):
        lab, hib, dec = METRICS[key]
        for i, s in enumerate(STRATEGIES):
            st = sc["strategies"][s][key]
            m, ci = st["mean"] * scale, st["ci95"] * scale
            ax.bar(i, m, 0.72, color=COLORS[s], yerr=ci, error_kw={"ecolor": "#52514e", "lw": 1, "capsize": 3},
                   edgecolor="#fcfcfb", linewidth=1.5)
            ax.text(i, m + ci + 0.01 * max(1e-9, ax.get_ylim()[1]), f"{m:.{dec}f}", ha="center", va="bottom",
                    fontsize=8, color="#0b0b0b")
        ax.set_xticks([])
        ax.set_title(lab.split(" (")[0] + (" ↑" if hib else " ↓"), fontsize=10, loc="left")
        ax.margins(y=0.18)

    head = next(s for s in res["scenarios"] if s["id"] == res["meta"]["headline_scenario"])
    keys = ["redistribution_rate", "deadline_success", "urgent_fulfilment", "jain_fairness",
            "hub_share_gap_abs", "mean_distance_km"]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.2))
    for ax, k in zip(axes.flat, keys):
        bars(ax, head, k)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[s]) for s in STRATEGIES]
    fig.legend(handles, [LABELS[s] for s in STRATEGIES], loc="lower center", ncol=4, frameon=False, fontsize=9)
    fig.suptitle(f"Headline scenario: hub-centred city, supply = 0.5 × demand "
                 f"({res['meta']['seeds_per_scenario']} seeds, mean ± 95% CI, simulated)", x=0.01, ha="left",
                 fontsize=11, color="#0b0b0b")
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    fig.savefig(os.path.join(OUT, "headline.png"), dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    for ax, key in zip(axes, ["urgent_fulfilment", "jain_fairness", "redistribution_rate"]):
        lab, hib, dec = METRICS[key]
        x0 = range(len(res["scenarios"]))
        for j, s in enumerate(STRATEGIES):
            vals = [sc["strategies"][s][key]["mean"] for sc in res["scenarios"]]
            cis = [sc["strategies"][s][key]["ci95"] for sc in res["scenarios"]]
            ax.bar([x + (j - 1.5) * 0.2 for x in x0], vals, 0.18, yerr=cis, color=COLORS[s],
                   error_kw={"ecolor": "#52514e", "lw": 0.8}, edgecolor="#fcfcfb", linewidth=1)
        ax.set_xticks(list(x0))
        ax.set_xticklabels([("hubs" if sc["geography"] == "central_hubs" else "uniform") + f"\n×{sc['supply_ratio']}"
                            for sc in res["scenarios"]], fontsize=8)
        ax.set_title(lab.split(" (")[0] + (" ↑" if hib else " ↓"), fontsize=10, loc="left")
    fig.legend(handles, [LABELS[s] for s in STRATEGIES], loc="lower center", ncol=4, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(os.path.join(OUT, "scenarios.png"), dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()

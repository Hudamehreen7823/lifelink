# LifeLink evaluation (simulated)

50 random seeds per scenario; values are mean ± 95% CI. All data is synthetic - see the assumptions at the end.


## central_hubs, supply = 0.5 × demand (headline)

| Metric | Oldest request first | Nearest first | LifeLink (weighted) | LifeLink + fairness |
|---|---|---|---|---|
| Redistribution rate (% of listed qty delivered) ↑ | 92.0 ± 0.9 | 91.7 ± 0.8 | 92.1 ± 0.8 | 92.3 ± 0.8 |
| Deadline success (% of accepted qty delivered in time) ↑ | 97.8 ± 0.4 | 98.1 ± 0.4 | 97.9 ± 0.4 | 98.1 ± 0.4 |
| Urgent need fulfilment (urgency 4-5, %) ↑ | 46.6 ± 2.1 | 46.8 ± 2.0 | 68.8 ± 1.9 | 69.2 ± 1.9 |
| Jain fairness index of fulfilment ratios (1 = equal) ↑ | 0.726 ± 0.011 | 0.572 ± 0.017 | 0.766 ± 0.010 | 0.843 ± 0.008 |
| Allocation vs need share deviation (0 = proportional) ↓ | 0.211 ± 0.008 | 0.331 ± 0.008 | 0.196 ± 0.007 | 0.143 ± 0.005 |
| Hub over/under-allocation vs their share of need (pts) ↓ | 3.8 ± 0.9 | 25.1 ± 1.2 | 6.9 ± 0.9 | 3.3 ± 0.6 |
| Time to acceptance (hours) ↓ | 5.12 ± 0.14 | 4.98 ± 0.15 | 3.88 ± 0.13 | 3.90 ± 0.13 |
| Mean delivery distance (km) ↓ | 12.7 ± 0.4 | 7.2 ± 0.3 | 11.0 ± 0.3 | 11.7 ± 0.3 |

Paired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):

| Metric | Mean diff ± 95% CI | Wins / seeds |
|---|---|---|
| Redistribution rate (% of listed qty delivered) | 0.6 ± 0.4 | 36/50 |
| Deadline success (% of accepted qty delivered in time) | -0.1 ± 0.3 | 25/50 |
| Urgent need fulfilment (urgency 4-5, %) | 22.4 ± 2.0 | 50/50 |
| Jain fairness index of fulfilment ratios (1 = equal) | 0.272 ± 0.017 | 50/50 |
| Allocation vs need share deviation (0 = proportional) | -0.188 ± 0.009 | 50/50 |
| Hub over/under-allocation vs their share of need (pts) | -21.8 ± 1.2 | 50/50 |
| Time to acceptance (hours) | -1.07 ± 0.15 | 49/50 |
| Mean delivery distance (km) | 4.6 ± 0.2 | 0/50 |

## central_hubs, supply = 1.0 × demand

| Metric | Oldest request first | Nearest first | LifeLink (weighted) | LifeLink + fairness |
|---|---|---|---|---|
| Redistribution rate (% of listed qty delivered) ↑ | 79.3 ± 1.0 | 76.8 ± 0.9 | 76.9 ± 0.9 | 77.3 ± 1.0 |
| Deadline success (% of accepted qty delivered in time) ↑ | 97.6 ± 0.4 | 97.4 ± 0.4 | 97.8 ± 0.4 | 97.8 ± 0.4 |
| Urgent need fulfilment (urgency 4-5, %) ↑ | 78.2 ± 2.0 | 76.6 ± 2.0 | 85.0 ± 1.5 | 84.8 ± 1.8 |
| Jain fairness index of fulfilment ratios (1 = equal) ↑ | 0.921 ± 0.009 | 0.883 ± 0.009 | 0.925 ± 0.008 | 0.945 ± 0.006 |
| Allocation vs need share deviation (0 = proportional) ↓ | 0.104 ± 0.005 | 0.133 ± 0.006 | 0.102 ± 0.005 | 0.090 ± 0.004 |
| Hub over/under-allocation vs their share of need (pts) ↓ | 2.8 ± 0.5 | 8.2 ± 0.6 | 3.9 ± 0.6 | 2.7 ± 0.4 |
| Time to acceptance (hours) ↓ | 6.15 ± 0.18 | 5.94 ± 0.18 | 5.56 ± 0.15 | 5.58 ± 0.15 |
| Mean delivery distance (km) ↓ | 12.7 ± 0.3 | 10.7 ± 0.3 | 12.1 ± 0.3 | 12.3 ± 0.3 |

Paired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):

| Metric | Mean diff ± 95% CI | Wins / seeds |
|---|---|---|
| Redistribution rate (% of listed qty delivered) | 0.5 ± 0.3 | 32/50 |
| Deadline success (% of accepted qty delivered in time) | 0.4 ± 0.3 | 33/50 |
| Urgent need fulfilment (urgency 4-5, %) | 8.2 ± 1.4 | 49/50 |
| Jain fairness index of fulfilment ratios (1 = equal) | 0.063 ± 0.008 | 50/50 |
| Allocation vs need share deviation (0 = proportional) | -0.043 ± 0.004 | 50/50 |
| Hub over/under-allocation vs their share of need (pts) | -5.5 ± 0.5 | 50/50 |
| Time to acceptance (hours) | -0.35 ± 0.17 | 38/50 |
| Mean delivery distance (km) | 1.6 ± 0.1 | 0/50 |

## central_hubs, supply = 1.5 × demand

| Metric | Oldest request first | Nearest first | LifeLink (weighted) | LifeLink + fairness |
|---|---|---|---|---|
| Redistribution rate (% of listed qty delivered) ↑ | 58.5 ± 0.6 | 57.6 ± 0.6 | 57.5 ± 0.6 | 57.6 ± 0.6 |
| Deadline success (% of accepted qty delivered in time) ↑ | 97.2 ± 0.5 | 97.3 ± 0.4 | 97.4 ± 0.5 | 97.5 ± 0.5 |
| Urgent need fulfilment (urgency 4-5, %) ↑ | 86.3 ± 1.8 | 86.0 ± 1.7 | 88.6 ± 1.4 | 89.0 ± 1.5 |
| Jain fairness index of fulfilment ratios (1 = equal) ↑ | 0.960 ± 0.006 | 0.951 ± 0.007 | 0.960 ± 0.006 | 0.967 ± 0.005 |
| Allocation vs need share deviation (0 = proportional) ↓ | 0.073 ± 0.005 | 0.083 ± 0.005 | 0.077 ± 0.005 | 0.073 ± 0.004 |
| Hub over/under-allocation vs their share of need (pts) ↓ | 2.6 ± 0.3 | 4.1 ± 0.4 | 3.1 ± 0.4 | 2.6 ± 0.3 |
| Time to acceptance (hours) ↓ | 6.44 ± 0.17 | 6.17 ± 0.17 | 5.97 ± 0.17 | 6.12 ± 0.18 |
| Mean delivery distance (km) ↓ | 12.7 ± 0.3 | 11.8 ± 0.3 | 12.4 ± 0.3 | 12.5 ± 0.3 |

Paired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):

| Metric | Mean diff ± 95% CI | Wins / seeds |
|---|---|---|
| Redistribution rate (% of listed qty delivered) | -0.0 ± 0.2 | 26/50 |
| Deadline success (% of accepted qty delivered in time) | 0.1 ± 0.3 | 32/50 |
| Urgent need fulfilment (urgency 4-5, %) | 3.0 ± 1.0 | 40/50 |
| Jain fairness index of fulfilment ratios (1 = equal) | 0.016 ± 0.005 | 47/50 |
| Allocation vs need share deviation (0 = proportional) | -0.010 ± 0.002 | 46/50 |
| Hub over/under-allocation vs their share of need (pts) | -1.6 ± 0.4 | 47/50 |
| Time to acceptance (hours) | -0.05 ± 0.16 | 29/50 |
| Mean delivery distance (km) | 0.7 ± 0.1 | 0/50 |

## uniform, supply = 0.5 × demand

| Metric | Oldest request first | Nearest first | LifeLink (weighted) | LifeLink + fairness |
|---|---|---|---|---|
| Redistribution rate (% of listed qty delivered) ↑ | 91.7 ± 0.9 | 91.4 ± 0.8 | 92.1 ± 0.8 | 91.9 ± 0.8 |
| Deadline success (% of accepted qty delivered in time) ↑ | 97.8 ± 0.4 | 97.8 ± 0.4 | 97.8 ± 0.4 | 97.8 ± 0.4 |
| Urgent need fulfilment (urgency 4-5, %) ↑ | 46.3 ± 2.0 | 46.7 ± 2.1 | 68.0 ± 1.8 | 68.0 ± 1.9 |
| Jain fairness index of fulfilment ratios (1 = equal) ↑ | 0.728 ± 0.012 | 0.710 ± 0.013 | 0.792 ± 0.008 | 0.851 ± 0.007 |
| Allocation vs need share deviation (0 = proportional) ↓ | 0.211 ± 0.008 | 0.242 ± 0.010 | 0.185 ± 0.006 | 0.140 ± 0.005 |
| Hub over/under-allocation vs their share of need (pts) ↓ | 3.2 ± 0.9 | 3.3 ± 0.7 | 2.7 ± 0.6 | 2.0 ± 0.4 |
| Time to acceptance (hours) ↓ | 5.30 ± 0.15 | 5.08 ± 0.13 | 4.03 ± 0.12 | 4.02 ± 0.15 |
| Mean delivery distance (km) ↓ | 22.1 ± 0.5 | 12.7 ± 0.4 | 17.4 ± 0.4 | 18.4 ± 0.4 |

Paired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):

| Metric | Mean diff ± 95% CI | Wins / seeds |
|---|---|---|
| Redistribution rate (% of listed qty delivered) | 0.5 ± 0.3 | 32/50 |
| Deadline success (% of accepted qty delivered in time) | 0.0 ± 0.3 | 20/50 |
| Urgent need fulfilment (urgency 4-5, %) | 21.3 ± 1.6 | 50/50 |
| Jain fairness index of fulfilment ratios (1 = equal) | 0.140 ± 0.012 | 50/50 |
| Allocation vs need share deviation (0 = proportional) | -0.103 ± 0.009 | 50/50 |
| Hub over/under-allocation vs their share of need (pts) | -1.4 ± 0.8 | 35/50 |
| Time to acceptance (hours) | -1.06 ± 0.14 | 49/50 |
| Mean delivery distance (km) | 5.7 ± 0.2 | 0/50 |

## uniform, supply = 1.0 × demand

| Metric | Oldest request first | Nearest first | LifeLink (weighted) | LifeLink + fairness |
|---|---|---|---|---|
| Redistribution rate (% of listed qty delivered) ↑ | 78.6 ± 1.0 | 77.1 ± 1.0 | 76.8 ± 1.0 | 76.9 ± 1.0 |
| Deadline success (% of accepted qty delivered in time) ↑ | 97.2 ± 0.4 | 97.5 ± 0.4 | 97.5 ± 0.4 | 97.4 ± 0.4 |
| Urgent need fulfilment (urgency 4-5, %) ↑ | 78.1 ± 2.0 | 76.5 ± 1.9 | 84.4 ± 1.6 | 85.0 ± 1.8 |
| Jain fairness index of fulfilment ratios (1 = equal) ↑ | 0.919 ± 0.009 | 0.918 ± 0.007 | 0.931 ± 0.007 | 0.947 ± 0.005 |
| Allocation vs need share deviation (0 = proportional) ↓ | 0.106 ± 0.005 | 0.111 ± 0.005 | 0.099 ± 0.005 | 0.090 ± 0.004 |
| Hub over/under-allocation vs their share of need (pts) ↓ | 2.8 ± 0.5 | 2.8 ± 0.4 | 2.7 ± 0.5 | 2.2 ± 0.3 |
| Time to acceptance (hours) ↓ | 6.37 ± 0.17 | 6.01 ± 0.18 | 5.67 ± 0.16 | 5.62 ± 0.15 |
| Mean delivery distance (km) ↓ | 22.0 ± 0.5 | 17.1 ± 0.5 | 19.8 ± 0.4 | 20.3 ± 0.4 |

Paired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):

| Metric | Mean diff ± 95% CI | Wins / seeds |
|---|---|---|
| Redistribution rate (% of listed qty delivered) | -0.2 ± 0.4 | 22/50 |
| Deadline success (% of accepted qty delivered in time) | -0.1 ± 0.3 | 22/50 |
| Urgent need fulfilment (urgency 4-5, %) | 8.5 ± 1.1 | 50/50 |
| Jain fairness index of fulfilment ratios (1 = equal) | 0.029 ± 0.005 | 48/50 |
| Allocation vs need share deviation (0 = proportional) | -0.021 ± 0.003 | 49/50 |
| Hub over/under-allocation vs their share of need (pts) | -0.6 ± 0.4 | 34/50 |
| Time to acceptance (hours) | -0.39 ± 0.15 | 39/50 |
| Mean delivery distance (km) | 3.2 ± 0.2 | 0/50 |

## uniform, supply = 1.5 × demand

| Metric | Oldest request first | Nearest first | LifeLink (weighted) | LifeLink + fairness |
|---|---|---|---|---|
| Redistribution rate (% of listed qty delivered) ↑ | 58.1 ± 0.6 | 57.5 ± 0.6 | 57.4 ± 0.6 | 57.4 ± 0.6 |
| Deadline success (% of accepted qty delivered in time) ↑ | 96.9 ± 0.5 | 97.2 ± 0.5 | 97.4 ± 0.4 | 97.2 ± 0.5 |
| Urgent need fulfilment (urgency 4-5, %) ↑ | 85.8 ± 1.7 | 85.4 ± 1.7 | 88.6 ± 1.5 | 88.8 ± 1.6 |
| Jain fairness index of fulfilment ratios (1 = equal) ↑ | 0.958 ± 0.006 | 0.957 ± 0.006 | 0.962 ± 0.006 | 0.967 ± 0.005 |
| Allocation vs need share deviation (0 = proportional) ↓ | 0.075 ± 0.005 | 0.079 ± 0.005 | 0.076 ± 0.005 | 0.073 ± 0.004 |
| Hub over/under-allocation vs their share of need (pts) ↓ | 2.6 ± 0.3 | 2.7 ± 0.4 | 2.5 ± 0.4 | 2.2 ± 0.3 |
| Time to acceptance (hours) ↓ | 6.57 ± 0.18 | 6.36 ± 0.22 | 6.09 ± 0.17 | 6.18 ± 0.19 |
| Mean delivery distance (km) ↓ | 22.0 ± 0.5 | 19.1 ± 0.4 | 20.6 ± 0.4 | 21.0 ± 0.4 |

Paired difference, LifeLink + fairness minus nearest-first (wins = seeds where LifeLink is better):

| Metric | Mean diff ± 95% CI | Wins / seeds |
|---|---|---|
| Redistribution rate (% of listed qty delivered) | -0.0 ± 0.2 | 22/50 |
| Deadline success (% of accepted qty delivered in time) | -0.1 ± 0.4 | 23/50 |
| Urgent need fulfilment (urgency 4-5, %) | 3.4 ± 0.9 | 46/50 |
| Jain fairness index of fulfilment ratios (1 = equal) | 0.011 ± 0.003 | 46/50 |
| Allocation vs need share deviation (0 = proportional) | -0.006 ± 0.002 | 43/50 |
| Hub over/under-allocation vs their share of need (pts) | -0.5 ± 0.2 | 39/50 |
| Time to acceptance (hours) | -0.19 ± 0.18 | 33/50 |
| Mean delivery distance (km) | 1.9 ± 0.2 | 0/50 |

## Weight sensitivity (headline scenario, LifeLink + fairness)

| Weights | Redistribution rate | Urgent need fulfilment | Jain fairness index of fulfilment ratios | Allocation vs need share deviation | Mean delivery distance |
|---|---|---|---|---|---|
| default (20/25/25/20/10) | 92.3 ± 0.8 | 69.2 ± 1.9 | 0.843 ± 0.008 | 0.143 ± 0.005 | 11.7 ± 0.3 |
| equal (20 each) | 92.3 ± 0.8 | 68.7 ± 2.0 | 0.845 ± 0.008 | 0.143 ± 0.005 | 11.7 ± 0.2 |
| proximity-heavy | 92.3 ± 0.8 | 65.6 ± 2.0 | 0.799 ± 0.010 | 0.175 ± 0.006 | 9.7 ± 0.2 |
| urgency-heavy | 92.5 ± 0.8 | 79.5 ± 1.9 | 0.821 ± 0.008 | 0.154 ± 0.006 | 12.4 ± 0.3 |
| need-heavy | 92.3 ± 0.8 | 57.6 ± 1.6 | 0.876 ± 0.007 | 0.124 ± 0.005 | 12.4 ± 0.2 |
| no proximity | 92.4 ± 0.8 | 69.8 ± 1.9 | 0.850 ± 0.007 | 0.141 ± 0.005 | 13.0 ± 0.3 |

## Fairness strength λ (headline scenario)

| λ | Redistribution rate | Urgent need fulfilment | Jain fairness index of fulfilment ratios | Allocation vs need share deviation | Mean delivery distance |
|---|---|---|---|---|---|
| 0.0 | 92.1 ± 0.8 | 68.8 ± 1.9 | 0.766 ± 0.010 | 0.196 ± 0.007 | 11.0 ± 0.3 |
| 0.1 | 92.4 ± 0.8 | 69.6 ± 2.0 | 0.812 ± 0.008 | 0.163 ± 0.005 | 11.4 ± 0.3 |
| 0.2 | 92.3 ± 0.8 | 69.2 ± 1.9 | 0.843 ± 0.008 | 0.143 ± 0.005 | 11.7 ± 0.3 |
| 0.4 | 92.3 ± 0.8 | 67.9 ± 1.9 | 0.878 ± 0.007 | 0.117 ± 0.005 | 12.3 ± 0.3 |
| 0.6 | 92.3 ± 0.8 | 65.2 ± 1.9 | 0.890 ± 0.006 | 0.101 ± 0.005 | 12.7 ± 0.3 |
| 0.8 | 92.3 ± 0.8 | 63.4 ± 1.8 | 0.894 ± 0.007 | 0.096 ± 0.005 | 12.9 ± 0.3 |

## Assumptions

- Recipients: 40 organisations. 25% are 'hubs' near the city centre (where providers also sit): they have 2.5x the weekly capacity and file about twice as many requests ('well-connected' organisations).
- Demand: Poisson number of requests per recipient over the period (mean 3, hubs 6); quantity log-normal (median 40, clipped 10-150); urgency 1-5 with probabilities 15/30/30/15/10%; 20% require condition 'good'.
- Supply: 160 listings spread uniformly in time; category, provider and condition random; quantities are rescaled per category so total supply = supply_ratio x total demand.
- Deadlines: food 6-48 h, other categories 3-14 days after listing.
- Acceptance: probability 0.95 - 0.004 x distance_km (floor 0.5). Response latency is exponential with mean 8/urgency hours. A rejection or timeout passes the listing to the next-ranked request.
- Delivery: volunteer delay uniform 1-10 h plus travel at 25 km/h. Deliveries that arrive after the deadline are lost (quantity wasted) and the request is re-opened.
- Requests expire 7 days after creation. Weekly capacity is enforced on a trailing 168 h window.
- Fairness history uses all allocations so far (the whole run is shorter than the 30-day window).

Synthetic data. These are simulation results, not measurements of real-world waste reduction.

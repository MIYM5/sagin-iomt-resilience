# Feasibility check for the journal extension

`bounds.py` asks whether an adaptive controller has room to improve on the best fixed policy. It computes bounds from the existing main-campaign traces (`data/main_iga`, 10 seeds, 2-h window), with no new simulations:

| Bound | Meaning |
|---|---|
| BF | best fixed policy per configuration, chosen with hindsight |
| SPO | single-path oracle: best policy per phase (attack window vs. rest), priority always on, radio asleep in gaps, 23 dBm only during the attack |
| TPO_GEO | adds a GEO fallback (one-way 270 ms, assumed) for messages generated while the UAV-LEO path is down |
| TPO_LEO2 | adds a second, independent LEO shell (visibility of another seed, i.e. another orbit phase) |

```bash
python3 analysis/feasibility/bounds.py data/main_iga results/feasibility
```

## Result (26 Nov 2026)

* Single path: no gain in alarm or ECG misses except under jamming (0.5 / 0.3 pp). The 20-85 % energy saving in sparse shells is reached by a static "priority + sleep" policy, so it is not headroom for adaptivity. Adaptive power under jamming saves 9 % at 90 mW idle power.
* Second path: a second LEO shell cuts alarms missing 100 ms from 19.5 % to 2.1 % at 240 satellites (shells overlap in gaps only 2.3 % of the time). GEO cannot meet 100 ms but removes alarms later than 1 s (19.2 % to 0 %). Using a fallback in every gap gives up the sleep saving, so the control problem is the per-message choice between waiting for the next predicted pass and paying for the fallback.

These are oracle bounds (hindsight, no switching cost); real controllers will reach less.

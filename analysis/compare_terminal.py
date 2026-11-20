#!/usr/bin/env python3
"""Terminal-profile sensitivity: main UAV terminal vs TR 38.821 handheld lower bound.

Usage: python3 compare_terminal.py <main_results> <handheld_results> <out_dir>
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plots import setting  # noqa: E402

ORDER = ["S0", "S1 (240 sats)", "S1 (120 sats)", "S1 (60 sats)", "S2", "S3"]
COLS = ["c1_miss", "c1_delay_p95_ms", "c2_miss", "c2_delay_p95_ms", "c2_availability", "c3_miss"]


def sat_link(rdir, n=40):
    """Median satellite-hop CNR and rate over a sample of runs (main scenarios only)."""
    out = []
    for f in sorted(glob.glob(os.path.join(rdir, "S0_P3_r*_satlink.csv")))[:n]:
        s = pd.read_csv(f)
        out.append(s)
    s = pd.concat(out)
    return dict(cnr_median_db=s.snr.median(), cnr_p5_db=s.snr.quantile(0.05),
                rate_median_mbps=s.rate.median() / 1e6, rate_p5_mbps=s.rate.quantile(0.05) / 1e6)


def main(md, hd, out):
    os.makedirs(out, exist_ok=True)
    frames = []
    for lab, d in (("main 33 dBm/10 dBi/1 MHz", md), ("handheld 23 dBm/0 dBi/360 kHz", hd)):
        m = pd.read_csv(os.path.join(d, "metrics.csv"))
        m = m.assign(setting=m.apply(setting, axis=1), terminal=lab)
        frames.append(m)
    m = pd.concat(frames)
    t = m.groupby(["setting", "policy", "terminal"])[COLS].mean().unstack("terminal")
    t = t.reindex([s for s in ORDER if s in t.index.get_level_values(0)], level=0)
    t.round(4).to_csv(os.path.join(out, "table_terminal_sensitivity.csv"))
    links = pd.DataFrame({"main": sat_link(md), "handheld": sat_link(hd)}).T
    with open(os.path.join(out, "table_terminal_sensitivity.txt"), "w") as f:
        f.write("Satellite hop (S0, P3 runs):\n" + links.round(2).to_string() + "\n\n")
        f.write(t.round(4).to_string())
        for lab, g in m.groupby("terminal"):
            v = g[(g.policy == "P4") & g.scenario.isin(["S0", "S1"])]
            err = v.c1_miss - v.c1_miss_pred
            f.write(f"\n\nAnalytical model, {lab}: corr {np.corrcoef(v.c1_miss, v.c1_miss_pred)[0, 1]:.4f}, "
                    f"MAE {err.abs().mean():.4f}")
    print(open(os.path.join(out, "table_terminal_sensitivity.txt")).read())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])

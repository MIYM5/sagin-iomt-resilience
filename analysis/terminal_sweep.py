#!/usr/bin/env python3
"""Three-point UAV terminal sweep: handheld (23 dBm EIRP), IGA main (37 dBm), HGA (43 dBm).

Usage: python3 terminal_sweep.py <handheld_dir> <iga_dir> <hga_dir> <out_dir>
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plots import setting  # noqa: E402

ORDER = ["S0", "S1 (240 sats)", "S1 (120 sats)", "S1 (60 sats)", "S2", "S3"]
TERM = ["Handheld 23 dBm", "IGA 37 dBm (main)", "HGA 43 dBm"]


def main(hh, iga, hga, out):
    frames, links = [], {}
    for lab, d in zip(TERM, (hh, iga, hga)):
        m = pd.read_csv(os.path.join(d, "metrics.csv"))
        frames.append(m.assign(setting=m.apply(setting, axis=1), terminal=lab))
        s = pd.concat(pd.read_csv(f) for f in glob.glob(os.path.join(d, "S0_P3_r*_satlink.csv")))
        links[lab] = dict(cnr_median_dB=s.snr.median(), cnr_p5_dB=s.snr.quantile(.05),
                          rate_median_Mbps=s.rate.median() / 1e6, rate_p5_Mbps=s.rate.quantile(.05) / 1e6)
    m = pd.concat(frames)
    t = (m.groupby(["setting", "policy", "terminal"])[["c1_miss", "c2_miss", "c2_availability"]]
         .mean().mul(100).unstack("terminal"))
    t = t.reindex([s for s in ORDER if s in t.index.get_level_values(0)], level=0)
    t = t.reindex(columns=TERM, level=1)
    t.round(2).to_csv(os.path.join(out, "table_terminal_sweep.csv"))
    with open(os.path.join(out, "table_terminal_sweep.txt"), "w") as f:
        f.write("Satellite hop (S0, P3 runs)\n" + pd.DataFrame(links).T.round(2).to_string() + "\n\n")
        f.write("Miss rates and C2 availability (%), mean of 10 seeds\n" + t.round(2).to_string() + "\n")
        for lab, g in m.groupby("terminal"):
            v = g[(g.policy == "P4") & g.scenario.isin(["S0", "S1"])]
            f.write(f"\nAnalytical model, {lab}: corr {np.corrcoef(v.c1_miss, v.c1_miss_pred)[0, 1]:.4f}, "
                    f"MAE {(v.c1_miss - v.c1_miss_pred).abs().mean():.4f}")
    print(open(os.path.join(out, "table_terminal_sweep.txt")).read())


if __name__ == "__main__":
    main(*sys.argv[1:5])

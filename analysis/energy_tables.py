#!/usr/bin/env python3
"""Energy tables for the paper.

Usage: python3 energy_tables.py <abstraction_results> <nr_results> <out_dir>
  table_energy_sensitivity.{csv,txt}: TR 45.820 total energy per run (J) for idle = 3/20/90 mW,
      and the P4 saving relative to P3 (same 10 dBm transmit power, always awake).
  table_energy_nr_tr38840.{csv,txt}: full-NR runs in TR 38.840 relative units, normalised to
      P3 in S0, with the UL share, plus the dB-interpolation bound for the 10 dBm UL state.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plots import setting  # noqa: E402

ORDER = ["S0", "S1 (240 sats)", "S1 (120 sats)", "S1 (60 sats)", "S2", "S3"]
SW = ["energyJ_idle3mW", "energyJ_idle20mW", "energyJ_idle90mW"]


def sensitivity(ab, out):
    m = pd.read_csv(os.path.join(ab, "metrics.csv"))
    m = m.assign(setting=m.apply(setting, axis=1))
    t = m.groupby(["setting", "policy"])[SW + ["txEnergyJ"]].mean()
    t.columns = ["idle 3 mW", "idle 20 mW", "idle 90 mW (main)", "TX part"]
    rows = []
    for s in ORDER:
        if s not in t.index.get_level_values(0):
            continue
        for p in ("P1", "P2", "P3", "P4"):
            r = t.loc[(s, p)].to_dict()
            r.update(setting=s, policy=p)
            for c in ("idle 3 mW", "idle 20 mW", "idle 90 mW (main)"):
                p3 = t.loc[(s, "P3"), c]
                r[f"vs P3 {c.split(' (')[0]}"] = 100 * (r[c] / p3 - 1)
            rows.append(r)
    d = pd.DataFrame(rows).set_index(["setting", "policy"])
    d.round(1).to_csv(os.path.join(out, "table_energy_sensitivity.csv"))
    with open(os.path.join(out, "table_energy_sensitivity.txt"), "w") as f:
        f.write("Radio energy per run (J), TR 45.820 Table 7.2.4.5-1; 'vs P3' = % difference\n")
        f.write(d.round(1).to_string())
    return d


def nr(nrd, out):
    m = pd.read_csv(os.path.join(nrd, "metrics.csv"))
    g = m.groupby(["scenario", "policy"])[["relE_total", "relE_ul", "relE_pdcch",
                                           "relE_total_dbinterp", "txTimeS"]].mean()
    ref = g.loc[("S0", "P3"), "relE_total"]
    refdb = g.loc[("S0", "P3"), "relE_total_dbinterp"]
    d = pd.DataFrame({
        "E_rel (x1e3 units*s)": g.relE_total / 1e3,
        "norm. to S0-P3": g.relE_total / ref,
        "UL share %": 100 * g.relE_ul / g.relE_total,
        "UL time s": g.txTimeS,
        "norm. (dB interp.)": g.relE_total_dbinterp / refdb,
    })
    d.round(3).to_csv(os.path.join(out, "table_energy_nr_tr38840.csv"))
    with open(os.path.join(out, "table_energy_nr_tr38840.txt"), "w") as f:
        f.write("Full-NR hub energy, TR 38.840 relative power model (UL 250@0dBm/700@23dBm, "
                "PDCCH-only 100, deep sleep 1)\n")
        f.write(d.round(3).to_string())
    return d


if __name__ == "__main__":
    os.makedirs(sys.argv[3], exist_ok=True)
    print(sensitivity(sys.argv[1], sys.argv[3]).round(1).to_string())
    print(nr(sys.argv[2], sys.argv[3]).round(3).to_string())

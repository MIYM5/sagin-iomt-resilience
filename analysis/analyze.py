#!/usr/bin/env python3
"""Per-run metrics for the SAGIN health scenario.

Usage: python3 analyze.py <out_dir>  -> writes metrics.csv and resilience.csv in <out_dir>
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import power  # noqa: E402

# Targets. C1/C2 from 3GPP TR 22.826 V17.2.0, Table 5.5.3.6-1 (cardiac telemetry outside the
# hospital): E2E latency < 100 ms, survival time < 1 s, availability 99.9999 %.
# Availability rule (TR 22.826 cl. 3.1 NOTE 6): service is unavailable when an expected message
# is not received within latency + survival time. C3 (store-and-forward) has no 3GPP target:
# evaluated against its 600 s generation period (see paper, Sect. 3.2).
DEADLINE = {1: 0.100, 2: 0.100, 3: 600.0}
SURVIVAL = 1.0
AVAIL_BUDGET = DEADLINE[2] + SURVIVAL  # 1.1 s
BIN = 60.0  # s, resilience time bins


def c2_availability(c2, T, patients):
    """TR 22.826 availability for the ECG stream, per patient, averaged.

    Unavailability starts when a message is not received within 1.1 s of generation and lasts
    until a later message is received within its own 1.1 s budget.
    """
    down_total = 0.0
    for _, x in c2.sort_values("gen").groupby("patient"):
        down_since = None
        for g, r in zip(x["gen"].to_numpy(), x["rx"].to_numpy()):
            ok = (not np.isnan(r)) and (r - g) <= AVAIL_BUDGET
            if not ok and down_since is None:
                down_since = g + AVAIL_BUDGET
            elif ok and down_since is not None:
                down_total += max(r - down_since, 0.0)
                down_since = None
        if down_since is not None:
            down_total += max(x["gen"].max() + AVAIL_BUDGET - down_since, 0.0)
    return 1.0 - down_total / (T * patients)


def gaps_from_vis(vis):
    """Return list of gap lengths (s) where the backhaul is down."""
    up = vis["up"].to_numpy()
    t = vis["t"].to_numpy()
    if len(t) < 2:
        return []
    step = np.median(np.diff(t))
    gaps, run = [], 0
    for u in up:
        if u == 0:
            run += 1
        elif run:
            gaps.append(run * step)
            run = 0
    if run:
        gaps.append(run * step)
    return gaps


def predicted_miss(gaps, T, tau, delta):
    slack = max(tau - delta, 0.0)
    return sum(max(gi - slack, 0.0) for gi in gaps) / T


def run_metrics(prefix):
    s = pd.read_csv(prefix + "_summary.csv").iloc[0].to_dict()
    gen = pd.read_csv(prefix + "_gen.csv")
    rx = pd.read_csv(prefix + "_rx.csv")
    vis = pd.read_csv(prefix + "_vis.csv")
    T = vis["t"].max() - vis["t"].min() + 1
    rx = rx.drop_duplicates(subset=["cls", "seq"])
    rx["delay"] = rx["rx"] - rx["gen"]
    m = gen.merge(rx[["cls", "seq", "rx", "delay"]], on=["cls", "seq"], how="left")
    out = dict(s)
    out["coverage"] = vis["up"].mean()
    gaps = gaps_from_vis(vis)
    out["n_gaps"] = len(gaps)
    out["mean_gap_s"] = float(np.mean(gaps)) if gaps else 0.0
    out["max_gap_s"] = float(np.max(gaps)) if gaps else 0.0
    delivered = m["rx"].notna()
    out["n_sats"] = int(s["planes"] * s["satsPerPlane"])
    # radio energy: TR 45.820 Table 7.2.4.5-1 (main: awake = RX active 90 mW) + idle sweep
    for k in ("txEnergyJ", "idleEnergyJ", "energyJ"):
        out[k + "_legacy"] = s[k]
    ttx, tawake, tsleep = power.state_times(s, T)
    out["txTimeS"], out["awakeS"], out["sleepS"] = ttx, tawake, tsleep
    e = power.tr45820_energy(s, T)
    out["txEnergyJ"], out["idleEnergyJ"], out["sleepEnergyJ"], out["energyJ"] = (
        e["tx"], e["idle"], e["sleep"], e["total"])
    for lab, w in power.IDLE_SWEEP_W.items():
        out[f"energyJ_idle{lab}"] = power.tr45820_energy(s, T, w)["total"]
    # TR 38.840 relative units (used for the full-NR runs; computed for every run)
    for interp in ("mw", "db"):
        r = power.tr38840_energy(s, T, interp)
        sfx = "" if interp == "mw" else "_dbinterp"
        out["relE_total" + sfx] = r["total"]
        if not sfx:
            out["relE_ul"], out["relE_pdcch"], out["relE_sleep"] = r["ul"], r["pdcch"], r["sleep"]
    out["energy_per_pkt_mJ"] = 1e3 * out["energyJ"] / max(delivered.sum(), 1)
    out["tx_energy_per_pkt_mJ"] = 1e3 * out["txEnergyJ"] / max(delivered.sum(), 1)

    for c in (1, 2):
        mc = m[m["cls"] == c]
        d = mc["delay"]
        ok = d.notna() & (d <= DEADLINE[c])
        out[f"c{c}_n"] = len(mc)
        out[f"c{c}_pdr"] = d.notna().mean()
        out[f"c{c}_miss"] = 1.0 - ok.mean()
        out[f"c{c}_delay_mean_ms"] = 1e3 * d.mean()
        out[f"c{c}_delay_p95_ms"] = 1e3 * d.quantile(0.95)
        out[f"c{c}_delay_median_ms"] = 1e3 * d.median()
    # C2 jitter: mean |D_i - D_{i-1}| per patient (RFC 3550 style, unsmoothed)
    c2 = m[(m["cls"] == 2) & m["delay"].notna()].sort_values(["patient", "seq"])
    out["c2_jitter_ms"] = 1e3 * c2.groupby("patient")["delay"].apply(lambda x: x.diff().abs().mean()).mean()
    out["c2_availability"] = c2_availability(m[m["cls"] == 2], T, m.loc[m["cls"] == 2, "patient"].nunique())
    # C3 file-level completion
    f = m[m["cls"] == 3]
    if len(f):
        g = f.groupby("fileId").agg(gen=("gen", "min"), n=("nFrag", "first"),
                                    got=("rx", "count"), last=("rx", "max"))
        g["done"] = g["got"] == g["n"]
        g["ct"] = g["last"] - g["gen"]
        ok = g["done"] & (g["ct"] <= DEADLINE[3])
        out["c3_files"] = len(g)
        out["c3_complete"] = g["done"].mean()
        out["c3_miss"] = 1.0 - ok.mean()
        out["c3_ct_mean_s"] = g.loc[g["done"], "ct"].mean()
    # analytical model (C1 under store-and-forward)
    delta = (out["c1_delay_median_ms"] / 1e3) if not np.isnan(out["c1_delay_median_ms"]) else 0.0
    out["c1_miss_pred"] = predicted_miss(gaps, T, DEADLINE[1], delta)
    # C2 on-time ratio per bin, used for resilience curves
    c2all = m[m["cls"] == 2].copy()
    c2all["ok"] = c2all["delay"].notna() & (c2all["delay"] <= DEADLINE[2])
    c2all["bin"] = (c2all["gen"] // BIN).astype(int)
    curve = c2all.groupby("bin")["ok"].mean()
    return out, curve


def main(d):
    rows, curves = [], {}
    for sfile in sorted(glob.glob(os.path.join(d, "*_summary.csv"))):
        prefix = sfile[: -len("_summary.csv")]
        try:
            r, curve = run_metrics(prefix)
        except Exception as e:  # incomplete run
            print("skip", prefix, e)
            continue
        r["tag"] = os.path.basename(prefix)
        rows.append(r)
        curves[r["tag"]] = curve
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(d, "metrics.csv"), index=False)
    cdf = pd.DataFrame(curves)
    cdf.index = cdf.index * BIN
    cdf.to_csv(os.path.join(d, "c2_curves.csv"))
    print(df.groupby(["scenario", "n_sats", "policy"])[
        ["coverage", "c1_miss", "c1_miss_pred", "c2_miss", "c2_availability", "c3_miss",
         "energy_per_pkt_mJ"]].mean().round(4))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")

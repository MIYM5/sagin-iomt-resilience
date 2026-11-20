#!/usr/bin/env python3
"""Paper figures from results/metrics.csv and results/c2_curves.csv.

Usage: python3 plots.py <results_dir> <fig_dir>
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# reference categorical palette, fixed order: P1..P4 -> slots 1..4; markers as secondary encoding
POL = ["P1", "P2", "P3", "P4"]
COL = {"P1": "#2a78d6", "P2": "#eb6834", "P3": "#1baf7a", "P4": "#eda100"}
MRK = {"P1": "o", "P2": "s", "P3": "^", "P4": "D"}
LBL = {"P1": "P1 max power", "P2": "P2 low power", "P3": "P3 priority", "P4": "P4 store-and-forward"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "savefig.dpi": 300, "savefig.bbox": "tight",
})


def ci95(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0


def setting(r):
    return f"S1 ({r.n_sats} sats)" if r.scenario == "S1" else r.scenario


def fig_validation(m, out):
    """Analytical alarm-miss prediction vs ns-3 measurement (P4, all coverage levels)."""
    d = m[(m.policy == "P4") & m.scenario.isin(["S0", "S1"])]
    fig, ax = plt.subplots(figsize=(3.4, 3.0))
    ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls="--", zorder=1)
    ax.scatter(d.c1_miss_pred, d.c1_miss, s=22, color=COL["P4"], edgecolor="white", lw=0.8, zorder=2)
    for n, g in d.groupby("n_sats"):
        ax.annotate(f"{n} sats", (g.c1_miss_pred.mean(), g.c1_miss.mean()), xytext=(6, -10),
                    textcoords="offset points", color=INK2, fontsize=8)
    ax.set_xlabel("Predicted C1 deadline-miss probability")
    ax.set_ylabel("Measured C1 deadline-miss rate (ns-3)")
    ax.set_xlim(-0.03, 1.0)
    ax.set_ylim(-0.03, 1.0)
    ax.set_aspect("equal")
    fig.savefig(os.path.join(out, "fig_model_validation.png"))
    fig.savefig(os.path.join(out, "fig_model_validation.pdf"))
    plt.close(fig)


def fig_tradeoff(m, out):
    """Energy vs alarm deadline-miss trade-off, one panel per setting."""
    settings = ["S0", "S1 (240 sats)", "S1 (120 sats)", "S2", "S3"]
    titles = {"S0": "S0 normal", "S2": "S2 jamming", "S3": "S3 DoS"}
    m = m.assign(setting=m.apply(setting, axis=1))
    fig, axes = plt.subplots(1, len(settings), figsize=(10, 2.6), sharey=False)
    for ax, s in zip(axes, settings):
        d = m[m.setting == s]
        for p in POL:
            g = d[d.policy == p]
            if g.empty:
                continue
            ax.errorbar(g.energyJ.mean(), 100 * g.c1_miss.mean(), xerr=ci95(g.energyJ),
                        yerr=100 * ci95(g.c1_miss), fmt=MRK[p], color=COL[p], ms=6, mec="white",
                        mew=0.8, elinewidth=1, capsize=0, label=LBL[p])
        ax.set_title(titles.get(s, s), fontsize=9, color=INK)
        ax.set_xlabel("Radio energy (J, TR 45.820)")
    axes[0].set_ylabel("C1 alarm deadline misses (%)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.10))
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_energy_tradeoff.png"))
    fig.savefig(os.path.join(out, "fig_energy_tradeoff.pdf"))
    plt.close(fig)


def fig_resilience(curves, m, out, scen, start, dur, fname, title):
    """C2 on-time ratio over time under a disruption window, mean across seeds."""
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.axvspan(start / 60, (start + dur) / 60, color="#f0efec", zorder=0)
    ax.text((start + dur) / 60 + 1, 50, title, ha="left", va="center", color=INK2, fontsize=8)
    for p in POL:
        cols = [c for c in curves.columns if c.startswith(f"{scen}_{p}_")]
        if not cols:
            continue
        y = 100 * curves[cols].mean(axis=1)
        ax.plot(curves.index / 60, y, color=COL[p], lw=2, label=LBL[p])
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("C2 ECG messages on time (%)")
    ax.set_ylim(0, 103)
    ax.set_xlim(0, 120)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=4, fontsize=8)
    fig.savefig(os.path.join(out, fname + ".png"))
    fig.savefig(os.path.join(out, fname + ".pdf"))
    plt.close(fig)


def resilience_table(curves, m, scen, start, dur):
    """Degradation depth, recovery time and resilience loss vs. the paired S0 run."""
    rows = []
    for p in POL:
        for col in [c for c in curves.columns if c.startswith(f"{scen}_{p}_")]:
            base_col = col.replace(f"{scen}_", "S0_", 1)
            if base_col not in curves:
                continue
            t = curves.index.to_numpy()
            q, b = curves[col].to_numpy(), curves[base_col].to_numpy()
            pre = np.nanmean(b[(t >= start - 600) & (t < start)])
            win = (t >= start) & (t < start + dur + 1800)
            depth = np.nanmax(np.clip(pre - q[win], 0, None)) if win.any() else 0
            loss = np.nansum(np.clip(b[win] - q[win], 0, None)) * (t[1] - t[0])
            after = (t >= start + dur) & (q >= 0.95 * pre)
            rec = (t[after][0] - (start + dur)) if after.any() else np.nan
            rows.append(dict(policy=p, depth=depth, recovery_s=rec, loss_s=loss))
    r = pd.DataFrame(rows)
    return r.groupby("policy").agg(depth_mean=("depth", "mean"), recovery_s=("recovery_s", "mean"),
                                   loss_s=("loss_s", "mean"))


def main(rdir, out):
    os.makedirs(out, exist_ok=True)
    m = pd.read_csv(os.path.join(rdir, "metrics.csv"))
    curves = pd.read_csv(os.path.join(rdir, "c2_curves.csv"), index_col=0)
    fig_validation(m, out)
    fig_tradeoff(m, out)
    fig_resilience(curves, m, out, "S2", 1800, 600, "fig_jamming_resilience", "jammer on")
    fig_resilience(curves, m, out, "S3", 3600, 600, "fig_dos_resilience", "DoS flood")
    m = m.assign(setting=m.apply(setting, axis=1))
    cols = ["coverage", "c1_miss", "c1_delay_p95_ms", "c2_miss", "c2_availability", "c3_miss",
            "txEnergyJ", "idleEnergyJ", "energyJ"]
    summ = m.groupby(["setting", "policy"])[cols].agg(["mean", ci95])
    summ.to_csv(os.path.join(out, "table_summary.csv"))
    with open(os.path.join(out, "table_resilience.txt"), "w") as f:
        for s, st, du in (("S2", 1800, 600), ("S3", 3600, 600)):
            f.write(f"== {s}\n{resilience_table(curves, m, s, st, du).round(3).to_string()}\n")
    v = m[(m.policy == "P4") & m.scenario.isin(["S0", "S1"])]
    err = (v.c1_miss - v.c1_miss_pred)
    with open(os.path.join(out, "model_validation.txt"), "w") as f:
        f.write(f"P4 runs: {len(v)}\nmean abs error: {err.abs().mean():.4f}\n"
                f"max abs error: {err.abs().max():.4f}\n"
                f"corr: {np.corrcoef(v.c1_miss, v.c1_miss_pred)[0, 1]:.4f}\n")
        f.write(v.groupby("n_sats")[["c1_miss", "c1_miss_pred", "coverage", "mean_gap_s"]]
                .mean().round(4).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

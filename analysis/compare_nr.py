#!/usr/bin/env python3
"""Full-NR hub hop vs. matched system-level abstraction (same band, timing and attacks).

Usage: python3 compare_nr.py <nr_results_dir> <abstraction_results_dir> <fig_dir>
Both dirs must already contain metrics.csv and c2_curves.csv from analyze.py.
"""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

POL = ["P1", "P2", "P3", "P4"]
COL = {"P1": "#2a78d6", "P2": "#eb6834", "P3": "#1baf7a", "P4": "#eda100"}
LBL = {"P1": "P1 max power", "P2": "P2 low power", "P3": "P3 priority", "P4": "P4 store-and-forward"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
ATK_START, ATK_DUR = 600, 600
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


def phase_on_time(rdir, scen, pol):
    """C2 on-time ratio before / during / after the attack window, per run, from raw logs."""
    rows = []
    for s in range(1, 100):
        pre = os.path.join(rdir, f"{scen}_{pol}_r{s}")
        if not os.path.exists(pre + "_gen.csv"):
            continue
        g = pd.read_csv(pre + "_gen.csv")
        r = pd.read_csv(pre + "_rx.csv").drop_duplicates(["cls", "seq"])
        m = g[g.cls == 2].merge(r[["cls", "seq", "rx"]], on=["cls", "seq"], how="left")
        m["ok"] = m.rx.notna() & ((m.rx - m.gen) <= 0.100)
        m["ph"] = pd.cut(m.gen, [-1, ATK_START, ATK_START + ATK_DUR, 1e9],
                         labels=["before", "during", "after"])
        d = m.groupby("ph", observed=True).ok.mean().to_dict()
        d["run"] = s
        rows.append(d)
    return pd.DataFrame(rows)


def main(nr_dir, ab_dir, out):
    os.makedirs(out, exist_ok=True)
    nr = pd.read_csv(os.path.join(nr_dir, "metrics.csv")).assign(model="Full NR")
    ab = pd.read_csv(os.path.join(ab_dir, "metrics.csv")).assign(model="Abstraction")
    both = pd.concat([nr, ab])
    cols = ["c1_miss", "c2_miss", "c2_availability", "c3_miss", "txEnergyJ"]
    t = both.groupby(["scenario", "policy", "model"])[cols].mean().unstack("model")
    t.to_csv(os.path.join(out, "table_nr_vs_abstraction.csv"))
    with open(os.path.join(out, "table_nr_vs_abstraction.txt"), "w") as f:
        f.write(t.round(4).to_string())

    # phase table (before/during/after the attack) for S2 and S3, both models
    rows = []
    for model, d in (("Full NR", nr_dir), ("Abstraction", ab_dir)):
        for sc in ("S2", "S3"):
            for p in POL:
                ph = phase_on_time(d, sc, p)
                if ph.empty:
                    continue
                rows.append(dict(model=model, scenario=sc, policy=p,
                                 **{k: ph[k].mean() for k in ("before", "during", "after") if k in ph}))
    pd.DataFrame(rows).round(4).to_csv(os.path.join(out, "table_attack_phases.csv"), index=False)

    # resilience curves under jamming: NR (solid) vs abstraction (dashed)
    cn = pd.read_csv(os.path.join(nr_dir, "c2_curves.csv"), index_col=0)
    cn = cn[cn.index < 1800]
    ca = pd.read_csv(os.path.join(ab_dir, "c2_curves.csv"), index_col=0)
    ca = ca[ca.index < 1800]
    for scen, title, fname in (("S2", "jammer on", "fig_nr_jamming"), ("S3", "DoS flood", "fig_nr_dos")):
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.6), sharey=True)
        for ax, (curves, name) in zip(axes, ((cn, "Full NR hub-UAV hop"), (ca, "System-level abstraction"))):
            ax.axvspan(ATK_START / 60, (ATK_START + ATK_DUR) / 60, color="#f0efec", zorder=0)
            for p in POL:
                c = [k for k in curves.columns if k.startswith(f"{scen}_{p}_")]
                if c:
                    ax.plot(curves.index / 60, 100 * curves[c].mean(axis=1), color=COL[p], lw=2,
                            label=LBL[p])
            ax.set_title(name, fontsize=9, color=INK)
            ax.set_xlabel("Time (min)")
            ax.set_xlim(0, 30)
            ax.set_ylim(0, 103)
            ax.text((ATK_START + ATK_DUR) / 60 + 0.5, 50, title, color=INK2, fontsize=8)
        axes[0].set_ylabel("C2 ECG messages on time (%)")
        h, l = axes[0].get_legend_handles_labels()
        fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=4, fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(out, fname + ".png"))
        fig.savefig(os.path.join(out, fname + ".pdf"))
        plt.close(fig)
    print(t.round(4).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])

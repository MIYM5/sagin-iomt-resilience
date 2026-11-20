#!/usr/bin/env python3
"""Paper figures at LNCS text width (12.2 cm = 4.8 in), 8 pt text, B/W-legible encodings."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("SAGIN_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from plots import ci95, setting
from compare_nr import phase_on_time

OUT = os.environ.get("SAGIN_FIGS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "figs"))
os.makedirs(OUT, exist_ok=True)
POL = ["P1", "P2", "P3", "P4"]
COL = {"P1": "#2a78d6", "P2": "#eb6834", "P3": "#1baf7a", "P4": "#b07a00"}
MRK = {"P1": "o", "P2": "s", "P3": "^", "P4": "D"}
LS = {"P1": "-", "P2": (0, (1, 1.2)), "P3": "--", "P4": "-."}
LBL = {"P1": "P1 max power", "P2": "P2 low power", "P3": "P3 priority", "P4": "P4 store-and-forward"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#dddcd8"
W = 4.8
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5, "legend.fontsize": 7.5, "font.family": "serif",
    "font.serif": ["DejaVu Serif"], "axes.edgecolor": INK2, "axes.linewidth": 0.6,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.spines.top": False,
    "axes.spines.right": False, "legend.frameon": False, "savefig.bbox": "tight",
    "pdf.fonttype": 42,
})
m = pd.read_csv(os.path.join(DATA, "main_iga", "metrics.csv"))
m = m.assign(setting=m.apply(setting, axis=1))


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".pdf"))
    fig.savefig(os.path.join(OUT, name + ".png"), dpi=300)
    plt.close(fig)


# Fig. 2: analytical model vs simulation (P4, all coverage levels)
d = m[(m.policy == "P4") & m.scenario.isin(["S0", "S1"])]
fig, ax = plt.subplots(figsize=(2.9, 2.6))
ax.plot([0, 1], [0, 1], color=INK2, lw=0.8, ls="--", zorder=1)
for n, g in d.groupby("n_sats"):
    ax.scatter(100 * g.c1_miss_pred, 100 * g.c1_miss, s=16, marker={60: "v", 120: "s", 240: "^", 528: "o"}[n],
               facecolor="white", edgecolor=INK, lw=0.7, zorder=2, label=f"{n} satellites")
ax.plot([0, 100], [0, 100], color=INK2, lw=0.8, ls="--", zorder=1)
ax.set_xlabel("Predicted alarm deadline misses (%)")
ax.set_ylabel("Simulated alarm deadline misses (%)")
ax.set_xlim(-3, 100)
ax.set_ylim(-3, 100)
ax.set_aspect("equal")
ax.legend(loc="lower right", handletextpad=0.2)
save(fig, "fig2_validation")

# Fig. 3: energy vs alarm misses, 2x2 settings
sets = [("S0", "S0 normal (528 sats)"), ("S1 (240 sats)", "S1 coverage gaps (240 sats)"),
        ("S1 (120 sats)", "S1 coverage gaps (120 sats)"), ("S2", "S2 jamming")]
fig, axes = plt.subplots(2, 2, figsize=(W, 3.5))
for ax, (s, t) in zip(axes.flat, sets):
    g0 = m[m.setting == s]
    for p in POL:
        g = g0[g0.policy == p]
        ax.errorbar(g.energyJ.mean(), 100 * g.c1_miss.mean(), xerr=ci95(g.energyJ),
                    yerr=100 * ci95(g.c1_miss), fmt=MRK[p], color=COL[p], mec=INK, mew=0.5, ms=5,
                    elinewidth=0.8, capsize=0, label=LBL[p])
    ax.set_title(t)
    ax.margins(x=0.15, y=0.25)
for ax in axes[1]:
    ax.set_xlabel("Hub radio energy per run (J)")
for ax in axes[:, 0]:
    ax.set_ylabel("Alarm misses (%)")
h, l = axes[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 1.04), ncol=4, columnspacing=1.0,
           handletextpad=0.3)
fig.tight_layout(h_pad=0.8, w_pad=1.0)
save(fig, "fig3_tradeoff")

# Fig. 4: jamming time series, full NR vs matched abstraction
ATK0, ATK1 = 600, 1200
fig, axes = plt.subplots(1, 2, figsize=(W, 2.15), sharey=True)
for ax, (d, name) in zip(axes, ((os.path.join(DATA, "full_nr"), "Full 5G NR hub-UAV hop"),
                                 (os.path.join(DATA, "abstraction_matched"), "System-level abstraction"))):
    c = pd.read_csv(os.path.join(d, "c2_curves.csv"), index_col=0)
    c = c[c.index < 1800]
    ax.axvspan(ATK0 / 60, ATK1 / 60, color="#efeeea", zorder=0, lw=0)
    for p in POL:
        cols = [k for k in c.columns if k.startswith(f"S2_{p}_")]
        ax.plot(c.index / 60, 100 * c[cols].mean(axis=1), color=COL[p], ls=LS[p], lw=1.3, label=LBL[p])
    ax.set_title(name)
    ax.set_xlabel("Time (min)")
    ax.set_xlim(0, 30)
    ax.set_ylim(-2, 103)
axes[0].set_ylabel("ECG on time (%)")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=4, columnspacing=1.0,
           handlelength=2.4, handletextpad=0.4)
fig.tight_layout(rect=(0, 0.06, 1, 1))
save(fig, "fig4_nr_jamming")

# Fig. 5: per-seed outcomes during the attack window (full NR)
fig, axes = plt.subplots(1, 2, figsize=(W, 1.95), sharey=True)
for ax, (sc, t) in zip(axes, (("S2", "S2 jamming"), ("S3", "S3 DoS flood"))):
    for i, p in enumerate(POL):
        y = 100 * phase_on_time(os.path.join(DATA, "full_nr"), sc, p).during.values
        x = i + np.linspace(-0.2, 0.2, len(y))
        ax.scatter(x, y, s=13, marker=MRK[p], facecolor=COL[p], edgecolor=INK, lw=0.4, zorder=3)
        ax.hlines(y.mean(), i - 0.32, i + 0.32, color=INK, lw=1.2, zorder=4)
    ax.set_xticks(range(4))
    ax.set_xticklabels(POL)
    ax.set_title(t)
    ax.set_ylim(-4, 104)
    ax.grid(axis="x", visible=False)
axes[0].set_ylabel("ECG on time during\nattack (%)")
fig.tight_layout()
save(fig, "fig5_nr_seeds")
print("ok")

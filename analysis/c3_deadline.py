#!/usr/bin/env python3
"""C3 (store-and-forward file) completion-time distribution and deadline sweep.

Usage: python3 c3_deadline.py <results_dir> <out_dir> <label>
Completion time = last fragment received - first fragment generated; files never completed count
as missing every deadline. The 600 s point equals the file generation period (stability bound).
"""
import glob
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plots import COL, LBL, POL, setting  # noqa: E402

DEADLINES = [10, 30, 60, 120, 300, 600]


def file_times(prefix):
    g = pd.read_csv(prefix + "_gen.csv")
    r = pd.read_csv(prefix + "_rx.csv").drop_duplicates(["cls", "seq"])
    f = g[g.cls == 3].merge(r[["cls", "seq", "rx"]], on=["cls", "seq"], how="left")
    a = f.groupby("fileId").agg(gen=("gen", "min"), n=("nFrag", "first"), got=("rx", "count"),
                                last=("rx", "max"))
    ct = np.where(a.got == a.n, a["last"] - a["gen"], np.inf)
    return ct


def main(rdir, out, label):
    os.makedirs(out, exist_ok=True)
    m = pd.read_csv(os.path.join(rdir, "metrics.csv"))
    m = m.assign(setting=m.apply(setting, axis=1))
    rows, cts = [], {}
    for _, r in m.iterrows():
        ct = file_times(os.path.join(rdir, r.tag))
        cts.setdefault((r.setting, r.policy), []).append(ct)
    for (s, p), lst in cts.items():
        ct = np.concatenate(lst)
        row = dict(setting=s, policy=p, files=len(ct), completed=np.isfinite(ct).mean(),
                   median_s=np.median(ct[np.isfinite(ct)]) if np.isfinite(ct).any() else np.nan,
                   p95_s=np.quantile(ct, 0.95) if np.isfinite(np.quantile(ct, 0.95)) else np.inf)
        for d in DEADLINES:
            row[f"miss@{d}s"] = (ct > d).mean()
        rows.append(row)
    t = pd.DataFrame(rows).sort_values(["setting", "policy"]).set_index(["setting", "policy"])
    t.round(4).to_csv(os.path.join(out, f"table_c3_deadline_{label}.csv"))
    with open(os.path.join(out, f"table_c3_deadline_{label}.txt"), "w") as f:
        f.write(f"C3 file completion ({label}); miss@D = share of files not complete within D s\n")
        f.write(t.round(3).to_string())
    # CDF figure: one panel per setting
    sets = [s for s in ["S0", "S1 (240 sats)", "S1 (120 sats)", "S1 (60 sats)", "S2", "S3"]
            if any(k[0] == s for k in cts)]
    fig, axes = plt.subplots(1, len(sets), figsize=(2.1 * len(sets), 2.4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, s in zip(axes, sets):
        for p in POL:
            if (s, p) not in cts:
                continue
            ct = np.sort(np.concatenate(cts[(s, p)]))
            y = np.arange(1, len(ct) + 1) / len(ct)
            ok = np.isfinite(ct)
            ax.step(np.maximum(ct[ok], 0.1), 100 * y[ok], where="post", color=COL[p], lw=1.6,
                    label=LBL[p])
        ax.axvline(600, color="#52514e", lw=0.8, ls="--")
        ax.set_xscale("log")
        ax.set_xlim(0.5, 3000)
        ax.set_ylim(0, 101)
        ax.set_title(s, fontsize=9)
        ax.set_xlabel("File completion time (s)")
    axes[0].set_ylabel("Files completed (%)")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=4, fontsize=8,
               frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, f"fig_c3_cdf_{label}.png"), dpi=300, bbox_inches="tight")
    fig.savefig(os.path.join(out, f"fig_c3_cdf_{label}.pdf"), bbox_inches="tight")
    print(t.round(3).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])

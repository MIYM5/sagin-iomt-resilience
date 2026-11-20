#!/usr/bin/env python3
"""Camera-ready sensitivity tables: jammer, DoS, elevation mask, priority ablation, NR jammer."""
import glob, os, re, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("SAGIN_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))

T = 2.776  # t(0.975, 4) for 5 seeds; overridden per n


def tci(x):
    from scipy import stats
    x = np.asarray(x, float); n = len(x)
    return x.mean(), (stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)) if n > 1 else 0.0


def phase(pre, a0, a1, cls=2, dl=0.100):
    g = pd.read_csv(pre + "_gen.csv"); r = pd.read_csv(pre + "_rx.csv").drop_duplicates(["cls", "seq"])
    m = g[g.cls == cls].merge(r[["cls", "seq", "rx"]], on=["cls", "seq"], how="left")
    ok = m.rx.notna() & ((m.rx - m.gen) <= dl)
    d = m[(m.gen >= a0) & (m.gen < a1)]
    return ok[d.index].mean() if len(d) else np.nan, (m.rx - m.gen)[d.index].quantile(0.95)


def attack_table(d, a0=600, a1=1200):
    rows = []
    for f in sorted(glob.glob(os.path.join(d, "*_summary.csv"))):
        pre = f[:-12]; tag = os.path.basename(pre)
        cfg, pol, run = re.match(r"(.*)_(P\w+)_r(\d+)$", tag).groups()
        on, p95 = phase(pre, a0, a1)
        rows.append(dict(cfg=cfg, policy=pol, run=int(run), on_time=on, p95_ms=1000 * p95))
    df = pd.DataFrame(rows)
    out = []
    for (c, p), g in df.groupby(["cfg", "policy"]):
        mu, ci = tci(g.on_time); out.append(dict(cfg=c, policy=p, n=len(g), on_time=100 * mu, ci=100 * ci,
                                              p95_ms=g.p95_ms.mean()))
    return pd.DataFrame(out)


def _cfg(m):
    return m.tag.str.replace(r"_P\w+_r\d+$", "", regex=True)


def mask_table():
    """Elevation-mask sweep (P4): coverage, gap length, simulated vs. predicted alarm misses."""
    m = pd.read_csv(os.path.join(DATA, "cr_mask", "metrics.csv"))
    t = m.groupby(["n_sats", "mask"]).agg(coverage=("coverage", "mean"), mean_gap_s=("mean_gap_s", "mean"),
                                          c1_miss=("c1_miss", "mean"), c1_miss_pred=("c1_miss_pred", "mean"))
    t[["coverage", "c1_miss", "c1_miss_pred"]] *= 100
    r = np.corrcoef(m.c1_miss, m.c1_miss_pred)[0, 1]
    mae = 100 * (m.c1_miss - m.c1_miss_pred).abs().mean()
    return t.sort_index(ascending=[False, True]), r, mae


def ablation_table():
    """Priority ablation at 10 dBm: P3F (FIFO, awake), P3H (hub-only priority), P3 (end to end), P4."""
    a = pd.read_csv(os.path.join(DATA, "cr_abl", "metrics.csv"))
    b = pd.read_csv(os.path.join(DATA, "main_iga", "metrics.csv"))
    b = b[b.policy.isin(["P3", "P4"])]
    m = pd.concat([a, b])
    m = m.assign(cfg=_cfg(m), policy=m.tag.str.extract(r"_(P\w+)_r\d+$")[0])  # P3H runs report policy=P3
    m = m[m.cfg.isin(["S0", "S1n240", "S1n120", "S2", "S3"])]
    rows = []
    for (c, p), g in m.groupby(["cfg", "policy"]):
        r = dict(cfg=c, policy=p, n=len(g))
        for k in ("c1_miss", "c2_miss"):
            mu, ci = tci(100 * g[k]); r[k] = mu; r[k + "_ci"] = ci
        rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    which = sys.argv[1]
    if which in ("jam", "dos", "nrjam"):
        print(attack_table(os.path.join(DATA, f"cr_{which}")).round(2).to_string(index=False))
    elif which == "mask":
        t, r, mae = mask_table()
        print(t.round(1).to_string()); print(f"model vs. simulation: r = {r:.3f}, MAE = {mae:.1f} pp")
    elif which == "abl":
        print(ablation_table().round(2).to_string(index=False))

"""Feasibility check for the journal extension.

Question: is there enough headroom above the best FIXED policy to justify an
adaptive (pass-aware, multi-path) controller?  Everything is computed from the
existing SUNRISE 2026 traces (results_v3: 10 seeds, 2-h window); no new runs.

Bounds per configuration (S0, S1n240, S1n120, S1n60, S2 jamming, S3 DoS):
  BF   best fixed policy (chosen per configuration with hindsight)
  SPO  single-path oracle: per seed and per phase (attack window vs. rest) the
       best policy's on-time outcome, priority always on, radio asleep in gaps,
       23 dBm only inside the attack window (an optimistic switching bound)
  TPO  two-path oracles for alarms and ECG generated while the UAV-LEO path is down
       GEO  : fallback over a GEO link (one-way latency LGEO)
       LEO2 : a second, independent LEO shell (visibility of another seed)
Times in the traces are relative to the start of the 2-h window.
"""
import sys, os, numpy as np, pandas as pd

D = sys.argv[1] if len(sys.argv) > 1 else "/root/results_v3"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/root/feas/out"
os.makedirs(OUT, exist_ok=True)
DL, SURV = 0.100, 1.1                 # deadline and latency + survival time (TR 22.826)
LGEO = 0.270                          # GEO one-way, ground-space-ground incl. processing (assumption)
LLEO = 0.020                          # LEO path delay when visible (SUNRISE runs: 10-30 ms)
WIN = {"S2": (1800, 2400), "S3": (3600, 4200)}
POL = ["P1", "P2", "P3", "P4"]
CFG = ["S0", "S1n240", "S1n120", "S1n60", "S2", "S3"]
IDLE = {"90mW": 0.09, "3mW": 0.003}


def load(cfg, pol, s):
    p = f"{D}/{cfg}_{pol}_r{s}"
    g = pd.read_csv(p + "_gen.csv"); r = pd.read_csv(p + "_rx.csv").drop_duplicates(["cls", "seq"])
    m = g[g.cls.isin([1, 2])].merge(r[["cls", "seq", "rx"]], on=["cls", "seq"], how="left")
    m["d"] = m.rx - m.gen
    sm = pd.read_csv(p + "_summary.csv").iloc[0]
    return m, sm


def down_intervals(vis):
    """Intervals [a,b) where the UAV-LEO path is down, from the 1-s visibility log."""
    v = vis.sort_values("t"); t = v.t.values; up = v.up.values.astype(bool)
    out, start = [], None
    for i in range(len(t)):
        if not up[i] and start is None: start = t[i]
        if up[i] and start is not None: out.append((start, t[i])); start = None
    if start is not None: out.append((start, t[-1] + 1))
    return out


def in_any(x, iv):
    if not iv: return np.zeros(len(x), bool)
    a = np.array([i[0] for i in iv]); b = np.array([i[1] for i in iv])
    k = np.searchsorted(a, x, side="right") - 1
    return (k >= 0) & (x < b[np.clip(k, 0, None)])


def energy(sm, idle_w, tx_scale=1.0, awake=None):
    awake = sm.awakeS if awake is None else awake
    txj = sm.txEnergyJ * tx_scale
    return txj + idle_w * max(awake - sm.txTimeS, 0) + 0.015e-3 * max(sm.windowS - awake, 0)


rows = []
for cfg in CFG:
    for s in range(1, 11):
        M, S = {}, {}
        for pol in POL:
            if not os.path.exists(f"{D}/{cfg}_{pol}_r{s}_summary.csv"): continue
            M[pol], S[pol] = load(cfg, pol, s)
        if len(M) < 4: continue
        vis = pd.read_csv(f"{D}/{cfg}_P4_r{s}_vis.csv")
        gaps = down_intervals(vis)
        # --- fixed policies
        for pol in POL:
            m = M[pol]
            r = dict(cfg=cfg, seed=s, kind=pol)
            for c in (1, 2):
                x = m[m.cls == c]
                r[f"c{c}_miss"] = 100 * (1 - ((x.d <= DL) & x.rx.notna()).mean())
                r[f"c{c}_late1s"] = 100 * (1 - ((x.d <= SURV) & x.rx.notna()).mean())
            for k, w in IDLE.items(): r[f"E_{k}"] = energy(S[pol], w)
            rows.append(r)
        # --- single-path oracle: per message, best policy in its phase
        a0, a1 = WIN.get(cfg[:2], (np.inf, np.inf))
        ref = M["P3"][["cls", "seq", "gen"]].copy()
        ok_on = {pol: M[pol].set_index(["cls", "seq"]).pipe(lambda z: (z.d <= DL) & z.rx.notna()) for pol in POL}
        ok_1s = {pol: M[pol].set_index(["cls", "seq"]).pipe(lambda z: (z.d <= SURV) & z.rx.notna()) for pol in POL}
        idx = ref.set_index(["cls", "seq"]).index
        att = ((ref.gen >= a0) & (ref.gen < a1)).values
        # phase-best policy chosen on the alarm+ECG on-time share of that phase (hindsight)
        def best(mask):
            sc = {pol: ok_on[pol].reindex(idx[mask]).fillna(False).mean() for pol in POL}
            return max(sc, key=sc.get)
        pa = best(att) if att.any() else "P3"; pn = best(~att)
        r = dict(cfg=cfg, seed=s, kind="SPO", pol_attack=pa, pol_normal=pn)
        on = np.where(att, ok_on[pa].reindex(idx).fillna(False).values, ok_on[pn].reindex(idx).fillna(False).values)
        o1 = np.where(att, ok_1s[pa].reindex(idx).fillna(False).values, ok_1s[pn].reindex(idx).fillna(False).values)
        for c in (1, 2):
            k = (ref.cls == c).values
            r[f"c{c}_miss"] = 100 * (1 - on[k].mean()); r[f"c{c}_late1s"] = 100 * (1 - o1[k].mean())
        # energy: sleep through gaps (P4 awake time), 10 dBm tx except 23 dBm inside the attack window
        f_att = 0 if not np.isfinite(a0) else (a1 - a0) / S["P3"].windowS
        txs = S["P3"].txEnergyJ * (1 - f_att) + S["P1"].txEnergyJ * f_att
        for k, w in IDLE.items():
            r[f"E_{k}"] = txs + w * max(S["P4"].awakeS - S["P3"].txTimeS, 0) + 0.015e-3 * max(S["P4"].windowS - S["P4"].awakeS, 0)
        rows.append(r)
        # --- two-path oracles: messages generated while the UAV-LEO path is down
        gen = ref.gen.values; down = in_any(gen, gaps)
        # second independent LEO shell = visibility of another seed (different orbit phase)
        s2 = s % 10 + 1
        gaps2 = down_intervals(pd.read_csv(f"{D}/{cfg}_P4_r{s2}_vis.csv"))
        down2 = in_any(gen, gaps2)
        for kind, fb_on, fb_1s in [("TPO_GEO", np.zeros_like(down), down),
                                    ("TPO_LEO2", down & ~down2, down & ~down2)]:
            r = dict(cfg=cfg, seed=s, kind=kind)
            on_t = np.where(down, fb_on, on); o1_t = np.where(down, fb_1s | o1, o1)
            for c in (1, 2):
                k = (ref.cls == c).values
                r[f"c{c}_miss"] = 100 * (1 - on_t[k].mean()); r[f"c{c}_late1s"] = 100 * (1 - o1_t[k].mean())
            r["share_down"] = 100 * down.mean(); r["share_down_both"] = 100 * (down & down2).mean()
            # energy: alarms-only fallback costs little; ECG fallback would keep the radio awake in gaps
            for kk, w in IDLE.items():
                base = [x for x in rows if x["cfg"] == cfg and x["seed"] == s and x["kind"] == "SPO"][0][f"E_{kk}"]
                gap_s = S["P4"].windowS - S["P4"].awakeS
                if kind == "TPO_LEO2":
                    gap_s = gap_s * (1 - (down & down2).sum() / max(down.sum(), 1))
                r[f"E_{kk}"] = base + w * gap_s          # awake on the fallback during UAV-LEO gaps
            rows.append(r)

T = pd.DataFrame(rows)
T.to_csv(f"{OUT}/bounds_per_seed.csv", index=False)
cols = ["c1_miss", "c2_miss", "c1_late1s", "c2_late1s", "E_90mW", "E_3mW"]
G = T.groupby(["cfg", "kind"])[cols].mean().round(2)
# best fixed policy per configuration: lowest C1 miss, then C2 miss, then energy (90 mW)
bf = []
for cfg in CFG:
    f = G.loc[cfg].loc[POL].sort_values(["c1_miss", "c2_miss", "E_90mW"])
    # within 0.1 pp of the best alarm and ECG miss, prefer the cheapest
    tol = f[(f.c1_miss <= f.c1_miss.min() + 0.1) & (f.c2_miss <= f.c2_miss.min() + 0.1)]
    pick = tol.sort_values("E_90mW").index[0] if len(tol) else f.index[0]
    bf.append((cfg, pick, *G.loc[(cfg, pick)].values))
BF = pd.DataFrame(bf, columns=["cfg", "BF_policy"] + cols).set_index("cfg")
print("=== per configuration, means over 10 seeds ==="); print(G.to_string())
print("\n=== best fixed policy per configuration (hindsight) ==="); print(BF.to_string())
summ = []
for cfg in CFG:
    b = BF.loc[cfg]
    for k in ["SPO", "TPO_GEO", "TPO_LEO2"]:
        o = G.loc[(cfg, k)]
        summ.append(dict(cfg=cfg, bound=k, BF=b.BF_policy,
                         dC1_pp=round(b.c1_miss - o.c1_miss, 2), dC2_pp=round(b.c2_miss - o.c2_miss, 2),
                         dC1_1s_pp=round(b.c1_late1s - o.c1_late1s, 2), dC2_1s_pp=round(b.c2_late1s - o.c2_late1s, 2),
                         dE90_pct=round(100 * (b.E_90mW - o.E_90mW) / b.E_90mW, 1),
                         dE3_pct=round(100 * (b.E_3mW - o.E_3mW) / b.E_3mW, 1)))
H = pd.DataFrame(summ)
print("\n=== headroom over the best fixed policy (positive = bound is better) ==="); print(H.to_string(index=False))
H.to_csv(f"{OUT}/headroom.csv", index=False); G.to_csv(f"{OUT}/bounds_mean.csv"); BF.to_csv(f"{OUT}/best_fixed.csv")

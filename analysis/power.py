"""Device radio power models for the SAGIN health study.

Two standard models, applied post hoc to the per-run radio state durations that the simulators log:

TR 45.820 (Table 7.2.4.5-1), absolute, used for the system-level abstraction runs:
    TX active   : P_out / 0.44 + 90 mW   (545 mW at +23 dBm; 44 % PA efficiency, 90 mW circuitry)
    RX active   : 90 mW   -> radio awake and listening for grants (connected mode), main setting
    light sleep : 3 mW    -> lower bound of the idle sweep
    deep sleep  : 0.015 mW -> P4 radio asleep through predicted coverage gaps
20 mW is the middle point of the idle sweep.

TR 38.840 (cl. 8.1.1, Tables 18-19), relative units, used for the full-NR runs:
    UL (PUSCH/PUCCH/SRS) : 250 at 0 dBm, 700 at 23 dBm
    PDCCH-only monitoring: 100  (every slot; 5G-LENA has no C-DRX, so an awake UE monitors each slot)
    deep sleep           : 1
    Reference: FR1, 30 kHz SCS (numerology 1, as simulated), 100 MHz. No bandwidth scaling is
    applied: all policies share the 10 MHz carrier, so policy ratios are unaffected.
    UL power between the two anchors is interpolated linearly in output power (mW), matching the
    P_out/eta + P_circ structure of the TR 45.820 model; dB-linear interpolation is the upper bound.

Legacy runs (summary without txTimeS/awakeS) are converted exactly: the simulators accrued
txEnergyJ = (P_out/0.30 + 0.08) * T_tx and idleEnergyJ = 0.02 * (T_awake - T_tx).
"""
import numpy as np

LEGACY_PA, LEGACY_CIRC, LEGACY_IDLE = 0.30, 0.08, 0.02

TR45820 = dict(pa_eff=0.44, circ_w=0.090, rx_w=0.090, light_w=0.003, deep_w=0.015e-3)
IDLE_SWEEP_W = {"3mW": 0.003, "20mW": 0.020, "90mW": 0.090}
MAIN_IDLE = "90mW"

TR38840 = dict(ul_0dbm=250.0, ul_23dbm=700.0, pdcch=100.0, deep=1.0)


def dbm_to_w(dbm):
    return 10 ** ((dbm - 30.0) / 10.0)


def state_times(s, window_s):
    """(T_tx, T_awake, T_sleep) in seconds from a run summary dict."""
    if "txTimeS" in s and "awakeS" in s and not np.isnan(s["txTimeS"]):
        ttx, tawake = s["txTimeS"], s["awakeS"]
    else:
        ttx = s["txEnergyJ"] / (dbm_to_w(s["hubTxDbm"]) / LEGACY_PA + LEGACY_CIRC)
        tawake = s["idleEnergyJ"] / LEGACY_IDLE + ttx
    tsleep = max(window_s - tawake, 0.0)
    return ttx, tawake, tsleep


def tr45820_energy(s, window_s, idle_w=None):
    """Absolute energy (J): dict with tx, idle, sleep and total under TR 45.820."""
    ttx, tawake, tsleep = state_times(s, window_s)
    idle_w = TR45820["rx_w"] if idle_w is None else idle_w
    etx = ttx * (dbm_to_w(s["hubTxDbm"]) / TR45820["pa_eff"] + TR45820["circ_w"])
    eidle = idle_w * max(tawake - ttx, 0.0)
    esleep = TR45820["deep_w"] * tsleep
    return dict(tx=etx, idle=eidle, sleep=esleep, total=etx + eidle + esleep)


def tr38840_ul(dbm, interp="mw"):
    lo, hi = TR38840["ul_0dbm"], TR38840["ul_23dbm"]
    if interp == "db":
        return lo + (hi - lo) * (dbm - 0.0) / 23.0
    p, p0, p1 = dbm_to_w(dbm), dbm_to_w(0.0), dbm_to_w(23.0)
    return lo + (hi - lo) * (p - p0) / (p1 - p0)


def tr38840_energy(s, window_s, interp="mw"):
    """Relative energy (relative power x s) under TR 38.840: dict with ul, pdcch, sleep, total."""
    ttx, tawake, tsleep = state_times(s, window_s)
    eul = tr38840_ul(s["hubTxDbm"], interp) * ttx
    epd = TR38840["pdcch"] * max(tawake - ttx, 0.0)
    esl = TR38840["deep"] * tsleep
    return dict(ul=eul, pdcch=epd, sleep=esl, total=eul + epd + esl)

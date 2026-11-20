# How the code works

This note explains the structure of the two ns-3 scenario programs and the analysis pipeline, so the results can be traced from a command-line option to a number in the paper.

## 1. Topology and data path

```
 IoMT wearables ─► Patient hub ──(A2G radio)──► UAV relay ──(UAV-to-LEO, bent pipe)──► Ground gateway ──(10 Mb/s backhaul)──► Hospital sink
                      ▲                                                                       ▲
                 Jammer (S2)                                                            DoS attacker (S3)
```

The hub, relay and sink are ns-3 `Application`s connected by UDP sockets. The two radio hops are where the variants differ; the gateway backhaul is always the native ns-3 point-to-point link with a DropTail queue, so the DoS flood competes with clinical traffic in a real IP queue.

## 2. System-level scenario (`sim/system-level/sagin-health.cc`, ns-3.49)

| Component | Role |
|---|---|
| `SimConfig` | All parameters in one struct (sites, constellation, radios, traffic, attacks, buffers). Every field is exposed as a command-line option. |
| `ClinicalHeader` | Custom ns-3 header carried by every packet: class (C1-C3), patient, sequence number, generation time, file id and fragment index. The sink uses it to measure end-to-end delay without any side channel. |
| `Visibility` | Every second, scans all satellites (ns-3 `LeoCircularOrbitMobilityModel`, Walker-delta shell) and selects the highest-elevation one above the mask at the UAV *and* visible from the gateway (bent pipe). Logs coverage per second and notifies listeners when the backhaul goes up or down. |
| `HubApp` | Generates the three traffic classes, queues them, and transmits over the hub-UAV hop. |
| `UavApp` | Relay buffer (100 packets) and transmission over the UAV-satellite hop. |
| `SinkApp` | Hospital endpoint; logs every received message with its generation time. |

**Traffic.** Ten patients each send a C1 alarm as a Poisson process (one per 300 s, 100 B) and a C2 ECG message every 0.5 s (150 B, 2.4 kbit/s single lead). The hub uploads one C3 record of 1 MB every 600 s in 1 kB fragments with an end-to-end retransmission timeout, so lost fragments are resent.

**Hub-UAV link.** Path loss follows TR 38.901 RMa LoS with the UAV at 100 m height and 600 m horizontal distance. The SINR includes the jammer in S2 (same path-loss model, placed `--jamDist` from the UAV). The rate is the attenuated Shannon bound of TR 36.942 A.1. Link adaptation targets 10 % BLER with up to four transmissions. When the SINR falls below the minimum, the hub treats the link as in outage and re-checks every 20 ms without spending radio energy.

**UAV-satellite link.** TR 38.811 NTN rural path loss (including scintillation) to the serving satellite, terminal EIRP 37 dBm by default (`--uavSatTx`, `--uavSatAnt`), satellite G/T 1.1 dB/K, 1 MHz carrier. With no serving satellite, the relay holds its buffer; the hub stops when the relay reports no buffer credit (hop-by-hop flow control).

**Policies.** They differ in three switches, set in `main()`:

| Policy | Hub power | Scheduling | Radio during gaps |
|---|---|---|---|
| P1 | 23 dBm | FIFO by generation time | awake |
| P2 | 0 dBm | FIFO | awake |
| P3 | 10 dBm | strict priority C1 > C2 > C3 at the hub **and** the relay; a full relay buffer pushes out the newest C3 fragment | awake |
| P4 | 10 dBm | FIFO, store-and-forward | asleep while no satellite is visible |
| P3F | 10 dBm | FIFO | awake (ablation) |
| P3 `--relayPrio=0` | 10 dBm | priority at the hub only | awake (ablation, "P3H") |

`HubApp::Pick()` chooses the next packet: the head of the highest non-empty class under priority, or the oldest head under FIFO.

**Attacks.** S2 switches the jammer on for 10 min (`--jamStart`, 20 dBm by default). S3 starts a 15 Mb/s UDP flood (`--dosRate`) from an attacker into the gateway backhaul queue (`--gwQueue` packets). S1 has no attack; it thins the shell (`--planes`, `--satsPerPlane`) so that coverage gaps appear.

**Energy accounting.** The hub logs its time transmitting (`txTimeS`) and its time awake (`awakeS`; P4 is awake only while the backhaul is up). Energy is not hard-wired: `analysis/power.py` applies the TR 45.820 or TR 38.840 model to these times afterwards, so the idle-power sweep needs no re-run.

**Link-budget check.** `--lbCheck=1` skips the scenario and reproduces the TR 38.821 Table 6.1.3.3-1 S-band link budget with the same propagation models, as a sanity check of the satellite hop.

**Run outputs.** `<out>_summary.csv` (configuration, coverage, state times, energy), `_gen.csv`, `_rx.csv`, `_vis.csv`, `_tx.csv`, `_satlink.csv` and `_drop_{hub,uav,bh}.csv` (see README).

## 3. Full-NR scenario (`sim/full-nr/sagin-health-nr.cc`, ns-3.48 + 5G-LENA NR-v5.1)

The same applications, header, visibility logic, satellite hop, backhaul and attacks, but the hub-UAV hop runs on the full 5G-LENA stack:

* the hub is an NR UE and the UAV an NR gNB at 3.5 GHz, 10 MHz, numerology 1; uplink scheduling, MCS selection and HARQ are NR's own;
* the hub keeps its three class queues and hands at most four application packets at a time to the NR stack (`inflightMax`); under P3 it always hands over the highest-priority packet, so priority takes effect before NR buffering instead of being lost in a single RLC queue;
* RLC runs in UM mode (`--rlc=um`, default); AM stalls under the heavy loss of the jamming scenario;
* the jammer (`JammerPhy`) is a barrage transmitter attached to the NR spectrum channel, so its interference passes through the same 3GPP spectrum propagation model and enters the gNB's SINR and HARQ decisions directly.

Runs cover a 30-min window with the attack at 600-1200 s. The `abstraction_matched` campaign runs the system-level program with the same band, bandwidth and timing, so the two radio models can be compared directly (paper Sect. 6.6).

## 4. Analysis pipeline (`analysis/`)

| Script | Input | Output |
|---|---|---|
| `analyze.py <dir>` | every run in `<dir>` | `metrics.csv`: per run, deadline misses per class (100 ms for C1/C2, 600 s for C3), delay percentiles, jitter, TR 22.826 availability (unavailable when a message is not received within 1.1 s), coverage and gap statistics, energy in both models, and the analytical alarm-miss prediction; `c2_curves.csv`: ECG on-time share per 60 s bin (resilience curves) |
| `power.py` | run summaries | TR 45.820 absolute energy (with the 3/20/90 mW idle sweep) and TR 38.840 relative energy |
| `plots.py` | `metrics.csv` | main table with 95 % Student-t intervals, model validation |
| `energy_tables.py` | main and NR metrics | idle-power sensitivity and NR relative-energy tables |
| `c3_deadline.py` | gen/rx traces | record completion-time distribution |
| `compare_nr.py` | NR and matched runs | abstraction vs. full-NR comparison, per-seed ECG on-time during the attack |
| `compare_terminal.py`, `terminal_sweep.py` | three terminal campaigns | UAV-terminal bracket (handheld / intermediate / high gain) |
| `cr_analysis.py jam\|dos\|nrjam\|mask\|abl` | sensitivity campaigns | Tables 7-8 (ECG on-time and p95 delay during the attack; mask sweep with model correlation and MAE; priority ablation) |
| `paper_figs.py` | all of the above | Figs. 2-5 |

**Analytical model.** `analyze.predicted_miss()` implements Eq. (1) of the paper. Gaps G_i are extracted from the visibility log (`gaps_from_vis`), and an alarm misses its deadline τ if it arrives in the last G_i − (τ − δ) seconds of a gap, where δ is the visible-path delay. Summing over gaps and dividing by the window T gives P_miss. Because alarms arrive independently of the satellite geometry, the fraction of alarms falling in gaps equals the fraction of time the gaps cover, so no arrival-rate parameter is needed. The script compares the prediction with the simulated P4 alarm misses for every run.

**Statistics.** Each configuration is run with independent seeds (10 for the main campaigns, 5 for sensitivity runs). The seed also randomises the start offset within the orbit, so each seed sees a different pass geometry. Tables report means with 95 % Student-t confidence intervals over seeds.

## 5. Reproducibility notes

* Runs are deterministic for a given `--run`; `scripts/*.sh` skip runs whose `_summary.csv` already exists.
* The high-gain terminal runs used 33 dBm + 10 dBi. The model depends only on EIRP, so these are equivalent to the 31 dBm + 12 dBi terminal described in the paper (43 dBm EIRP).
* Neither ns-3 tree is modified; the scenarios are single `scratch/` programs.

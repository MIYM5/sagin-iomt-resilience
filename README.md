# Clinical resilience of IoMT traffic over a UAV-assisted LEO backhaul

Simulation code, run scripts, analysis pipeline and result summaries for the paper

> M. I. Younas, M. J. Iqbal, A. H. Sodhro, M. Iqbal and J.-Y. Pan, "Toward Clinical Resilience of Remote Patient Monitoring over UAV-Assisted LEO Backhaul under Coverage Gaps, Jamming and Denial of Service," in *Secure and Resilient Digital Transformation of Healthcare (SUNRISE 2026)*, Communications in Computer and Information Science, Springer, 2026 (in press).

The study asks whether a remote patient-monitoring hub can meet the 3GPP TR 22.826 cardiac-telemetry targets (100 ms latency, 1 s survival time, 99.9999 % availability) when its only backhaul is a UAV relay over a bent-pipe LEO satellite. Three traffic classes (C1 emergency alarms, C2 continuous ECG, C3 store-and-forward records) are carried under four hub policies (P1-P4) and four conditions: normal operation (S0), coverage gaps in sparse shells (S1), jamming of the hub-UAV link (S2) and a DoS flood on the ground-gateway backhaul (S3).

Two simulators are used:

| Variant | Simulator | Hub-UAV hop | Used for |
|---|---|---|---|
| `sim/system-level` | ns-3.49 | TR 38.901 RMa LoS path loss, attenuated Shannon (TR 36.942) | Main results, coverage sweep, terminal bracket, sensitivity, ablation |
| `sim/full-nr` | ns-3.48 + 5G-LENA NR-v5.1 | Full 5G NR stack (RLC UM) | Protocol-level check of the jamming and DoS results |

Both share the satellite hop: TR 38.811 NTN rural path loss with scintillation, a Walker-delta 53°:528/24/1 shell at 550 km (thinned to 60/120/240 satellites for S1), visibility updated every 1 s, the highest-elevation satellite visible at both the UAV and the gateway as server, hard handover and no inter-satellite links.

## Repository layout

```
sim/system-level/sagin-health.cc     system-level scenario (ns-3.49)
sim/full-nr/sagin-health-nr.cc       full-NR scenario (ns-3.48 + 5G-LENA)
scripts/env.sh                       paths and parallelism (NS3_DIR, NR_DIR, DATA, JOBS)
scripts/build.sh                     copies the scenarios into the ns-3 trees and builds them
scripts/run_main.sh                  main campaign            -> data/main_iga, abstraction_matched, full_nr
scripts/run_terminal.sh              UAV-terminal bracket     -> data/terminal_hga, terminal_handheld
scripts/run_sensitivity.sh           sensitivity + ablation   -> data/cr_jam, cr_dos, cr_mask, cr_abl, cr_nrjam
scripts/analyze_all.sh               metrics, tables and figures -> out/
docs/CODE.md                         how the simulators and the analysis work
docs/tutorial/                       beginner's tutorial on the paper (PDF + LaTeX source)
analysis/                            Python analysis (metrics, energy models, analytical model, figures)
results/summaries/<campaign>/        per-run summaries, metrics.csv and ECG curves for every campaign
results/tables/                      LaTeX tables as they appear in the paper
```

All runs skip outputs that already exist, so an interrupted campaign can simply be restarted. A walkthrough of the simulators and the analysis pipeline is in [`docs/CODE.md`](docs/CODE.md), and a beginner-level tutorial that explains the whole study, with every term defined, is in [`docs/tutorial/`](docs/tutorial/Tutorial_UAV-LEO-IoMT_Resilience.pdf).

## Requirements

* Linux, a C++20 compiler, CMake >= 3.13, Python >= 3.10
* [ns-3.49](https://www.nsnam.org/releases/ns-3-49/) (unmodified; the LEO orbit and NTN models are part of the release)
* [ns-3.48](https://www.nsnam.org/releases/ns-3-48/) with [5G-LENA](https://gitlab.com/cttc-lena/nr) release NR-v5.1 (branch `5g-lena-v5.1.y`, DOI 10.5281/zenodo.21770621) in `contrib/nr`
* Python packages in `requirements.txt` (tested with pandas 3.0, numpy 2.5, scipy 1.18, matplotlib 3.11)

## Reproducing the results

```bash
# 1. simulators
git clone https://gitlab.com/nsnam/ns-3-dev.git ~/ns-3.49 && git -C ~/ns-3.49 checkout ns-3.49
git clone https://gitlab.com/nsnam/ns-3-dev.git ~/ns-3.48 && git -C ~/ns-3.48 checkout ns-3.48
git clone https://gitlab.com/cttc-lena/nr.git ~/ns-3.48/contrib/nr && git -C ~/ns-3.48/contrib/nr checkout 5g-lena-v5.1.y
pip install -r requirements.txt

# 2. build the two scenarios
NS3_DIR=~/ns-3.49 NR_DIR=~/ns-3.48 scripts/build.sh

# 3. run (set JOBS to the number of free cores)
JOBS=8 scripts/run_main.sh
JOBS=8 scripts/run_terminal.sh
JOBS=8 scripts/run_sensitivity.sh

# 4. analyse
scripts/analyze_all.sh
```

Every run is deterministic for a given `--run` seed. Instead of re-running, the raw traces used in the paper can be downloaded from Zenodo (see below) and extracted into `data/`; step 4 then reproduces every table and figure.

A single run is started directly, for example:

```bash
~/ns-3.49/build/scratch/sagin-health/ns3.49-sagin-health-optimized \
    --policy=P3 --scenario=S2 --planes=24 --satsPerPlane=22 --run=1 --out=data/test/S2_P3_r1
```

Main options: `--policy` (P1 23 dBm FIFO, P2 0 dBm FIFO, P3 10 dBm end-to-end priority, P4 10 dBm FIFO with store-and-forward sleep, P3F 10 dBm FIFO always awake), `--relayPrio=0` (hub-only priority), `--scenario` (S0-S3), `--planes`, `--satsPerPlane`, `--mask`, `--gwMask`, `--jamDbm`, `--jamDist`, `--dosRate`, `--gwQueue`, `--uavSatTx`, `--uavSatAnt`, `--satBw`, `--window`, `--run`. Run with `--PrintHelp` for the full list.

## Where each result comes from

| Paper | Campaign (`data/...`) | Script |
|---|---|---|
| Table 5, Figs. 2-3 (main results, energy) | `main_iga` | `plots.py`, `energy_tables.py`, `paper_figs.py` |
| Eq. (1) validation, Fig. 2 | `main_iga` (P4, S1) | `analyze.py`, `plots.py` |
| Sect. 6.4 C3 completion times | `main_iga` | `c3_deadline.py` |
| Sect. 6.5 terminal bracket | `terminal_hga`, `main_iga`, `terminal_handheld` | `terminal_sweep.py`, `compare_terminal.py` |
| Table 6, Figs. 4-5 (abstraction vs. full NR) | `abstraction_matched`, `full_nr` | `compare_nr.py`, `paper_figs.py` |
| Table 7 (sensitivity) | `cr_jam`, `cr_dos`, `cr_nrjam`, `cr_mask` | `cr_analysis.py jam / dos / nrjam / mask` |
| Table 8 (priority ablation) | `cr_abl`, `main_iga` | `cr_analysis.py abl` |

The mask and ablation tables can be checked straight from this repository, without the raw traces:

```bash
SAGIN_DATA=results/summaries python3 analysis/cr_analysis.py mask
SAGIN_DATA=results/summaries python3 analysis/cr_analysis.py abl
```

## Output files of a run

For an output prefix `<out>`, each run writes `<out>_summary.csv` (configuration, radio state durations, energy), `<out>_gen.csv` and `<out>_rx.csv` (every generated and received message with timestamps), `<out>_vis.csv` (serving satellite and elevation per second), `<out>_tx.csv` (hub transmissions), `<out>_satlink.csv` (UAV-satellite SNR, rate and propagation delay) and `<out>_drop_{hub,uav,bh}.csv` (queue drops per node).

## Energy models

Energy is that of the hub radio only. System-level runs use 3GPP TR 45.820 Table 7.2.4.5-1 (transmit P_out/0.44 + 90 mW, receive 90 mW, deep sleep 0.015 mW) with an idle sweep of 3/20/90 mW; full-NR runs use the relative power units of 3GPP TR 38.840 (UL 250 at 0 dBm and 700 at 23 dBm, PDCCH monitoring 100, deep sleep 1). Both are applied after the run to the logged state durations (`analysis/power.py`).

## Data

Raw traces (message-level, about 1,200 runs): Zenodo, DOI [10.5281/zenodo.XXXXXXX](https://doi.org/10.5281/zenodo.XXXXXXX).

## Citation

If you use this code or data, please cite the paper above and this repository (see `CITATION.cff`).

## Licence

Code: GNU General Public License v2.0 only (as ns-3). Data and result files: CC BY 4.0. See `LICENSE` and `LICENSE-DATA`.

## Contact

Muhammad Irfan Younas, Institute of Space Science and Technology, University of Karachi, and Sukkur IBA University, Pakistan. irfan.younas@iba-suk.edu.pk

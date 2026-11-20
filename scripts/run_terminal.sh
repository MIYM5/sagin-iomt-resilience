#!/usr/bin/env bash
# UAV-terminal bracket (Sect. 6.5): high-gain (43 dBm EIRP) and TR 38.821 handheld (23 dBm, 0 dBi, 360 kHz).
# The high-gain runs used 33 dBm + 10 dBi; the model depends only on EIRP, so this equals 31 dBm + 12 dBi.
set -u
source "$(dirname "$0")/env.sh"
for pair in "terminal_hga|--uavSatTx=33 --uavSatAnt=10" "terminal_handheld|--uavSatTx=23 --uavSatAnt=0 --satBw=360e3"; do
  d=$DATA/${pair%%|*}; x=${pair#*|}; mkdir -p "$d"
  for s in $(seq 1 10); do for p in P1 P2 P3 P4; do
    for sc in S0 S2 S3; do add "$d/${sc}_${p}_r$s" "$NS3 --policy=$p --scenario=$sc --planes=24 --satsPerPlane=22 --run=$s $x"; done
    for g in "6 10" "12 10" "12 20"; do set -- $g; add "$d/S1n$(( $1 * $2 ))_${p}_r$s" "$NS3 --policy=$p --scenario=S1 --planes=$1 --satsPerPlane=$2 --run=$s $x"; done
  done; done
done
run_jobs

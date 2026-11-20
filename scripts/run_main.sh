#!/usr/bin/env bash
# Main campaign (Tables 5-6, Figs. 2-5): 10 seeds x P1-P4.
#   main_iga            : system-level, 2-h window, S0/S2/S3 on the 528-sat shell, S1 on 60/120/240 sats
#   abstraction_matched : system-level matched to the NR runs (3.5 GHz, 10 MHz, 30-min window, attacks 600-1200 s)
#   full_nr             : 5G-LENA hub-UAV hop, same timing
set -u
source "$(dirname "$0")/env.sh"
mkdir -p "$DATA"/{main_iga,abstraction_matched,full_nr}
SHELL528="--planes=24 --satsPerPlane=22"
for s in $(seq 1 10); do for p in P1 P2 P3 P4; do
  for sc in S0 S2 S3; do add "$DATA/main_iga/${sc}_${p}_r$s" "$NS3 --policy=$p --scenario=$sc $SHELL528 --run=$s"; done
  for g in "6 10" "12 10" "12 20"; do set -- $g; add "$DATA/main_iga/S1n$(( $1 * $2 ))_${p}_r$s" "$NS3 --policy=$p --scenario=S1 --planes=$1 --satsPerPlane=$2 --run=$s"; done
  for sc in S0 S2 S3; do add "$DATA/abstraction_matched/${sc}_${p}_r$s" "$NS3 --policy=$p --scenario=$sc --run=$s --window=1800 --jamStart=600 --dosStart=600 --hubFcGHz=3.5 --hubBw=10e6 $SHELL528 --drain=120"; done
  for sc in S0 S2 S3; do add "$DATA/full_nr/${sc}_${p}_r$s" "$NR --policy=$p --scenario=$sc --run=$s"; done
done; done
run_jobs

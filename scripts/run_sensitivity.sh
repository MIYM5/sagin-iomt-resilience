#!/usr/bin/env bash
# Sensitivity and ablation campaigns (Sects. 6.7-6.8, Tables 7-8).
set -u
source "$(dirname "$0")/env.sh"
mkdir -p "$DATA"/{cr_jam,cr_dos,cr_mask,cr_abl,cr_nrjam}
SHORT="--window=1800 --jamStart=600 --dosStart=600 --drain=120 --planes=24 --satsPerPlane=22"
for s in 1 2 3 4 5; do for p in P1 P3; do
  for jp in 10 20 30; do add "$DATA/cr_jam/J${jp}_D300_${p}_r$s" "$NS3 --policy=$p --scenario=S2 --run=$s $SHORT --jamDbm=$jp --jamDist=300"; done
  for jd in 150 600; do add "$DATA/cr_jam/J20_D${jd}_${p}_r$s" "$NS3 --policy=$p --scenario=S2 --run=$s $SHORT --jamDbm=20 --jamDist=$jd"; done
  for dr in 11 15 20; do add "$DATA/cr_dos/R${dr}_Q100_${p}_r$s" "$NS3 --policy=$p --scenario=S3 --run=$s $SHORT --dosRate=${dr}Mbps --gwQueue=100"; done
  for q in 50 200; do add "$DATA/cr_dos/R15_Q${q}_${p}_r$s" "$NS3 --policy=$p --scenario=S3 --run=$s $SHORT --dosRate=15Mbps --gwQueue=$q"; done
  for jp in 10 30; do add "$DATA/cr_nrjam/J${jp}_${p}_r$s" "$NR --policy=$p --scenario=S2 --run=$s --jamDbm=$jp"; done
done; done
for s in 1 2 3 4 5; do for m in 15 25 35; do for g in "12 10" "12 20"; do set -- $g
  add "$DATA/cr_mask/M${m}_n$(( $1 * $2 ))_P4_r$s" "$NS3 --policy=P4 --scenario=S1 --run=$s --planes=$1 --satsPerPlane=$2 --mask=$m --gwMask=$m"
done; done; done
for s in $(seq 1 10); do
  for sc in S0 S2 S3; do
    add "$DATA/cr_abl/${sc}_P3F_r$s" "$NS3 --policy=P3F --scenario=$sc --run=$s --planes=24 --satsPerPlane=22"
    add "$DATA/cr_abl/${sc}_P3H_r$s" "$NS3 --policy=P3 --relayPrio=0 --scenario=$sc --run=$s --planes=24 --satsPerPlane=22"
  done
  for g in "12 10" "12 20"; do set -- $g; n=$(( $1 * $2 ))
    add "$DATA/cr_abl/S1n${n}_P3F_r$s" "$NS3 --policy=P3F --scenario=S1 --run=$s --planes=$1 --satsPerPlane=$2"
    add "$DATA/cr_abl/S1n${n}_P3H_r$s" "$NS3 --policy=P3 --relayPrio=0 --scenario=S1 --run=$s --planes=$1 --satsPerPlane=$2"
  done
done
run_jobs

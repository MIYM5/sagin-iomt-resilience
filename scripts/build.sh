#!/usr/bin/env bash
# Copy the two scenario programs into the ns-3 trees and build them (optimized profile).
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
source "$HERE/scripts/env.sh"
mkdir -p "$NS3_DIR/scratch/sagin-health" "$NR_DIR/scratch/sagin-health-nr"
cp "$HERE/sim/system-level/sagin-health.cc" "$NS3_DIR/scratch/sagin-health/"
cp "$HERE/sim/full-nr/sagin-health-nr.cc" "$NR_DIR/scratch/sagin-health-nr/"
(cd "$NS3_DIR" && ./ns3 configure --build-profile=optimized --enable-modules=core,network,internet,mobility,propagation,antenna,applications,point-to-point && ./ns3 build scratch/sagin-health/sagin-health)
(cd "$NR_DIR" && ./ns3 configure --build-profile=optimized --enable-modules=nr && ./ns3 build scratch/sagin-health-nr/sagin-health-nr)
echo "built"

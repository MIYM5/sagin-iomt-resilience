# Paths used by all run scripts. Override any of them before sourcing, e.g.
#   NS3_DIR=$HOME/ns-3.49 NR_DIR=$HOME/ns-3.48 DATA=$PWD/data source scripts/env.sh
: "${NS3_DIR:=$HOME/ns-3.49}"          # ns-3.49 tree with sim/system-level copied to scratch/sagin-health
: "${NR_DIR:=$HOME/ns-3.48}"           # ns-3.48 tree with 5G-LENA NR-v5.1 in contrib/nr and sim/full-nr in scratch/sagin-health-nr
: "${DATA:=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data}"
: "${JOBS:=2}"                         # parallel simulations
NS3=$(ls "$NS3_DIR"/build/scratch/sagin-health/ns3.49-sagin-health-optimized 2>/dev/null || ls "$NS3_DIR"/build/scratch/sagin-health/ns3.49-sagin-health* | head -1)
NR=$(ls "$NR_DIR"/build/scratch/sagin-health-nr/ns3.48-sagin-health-nr-optimized 2>/dev/null || ls "$NR_DIR"/build/scratch/sagin-health-nr/ns3.48-sagin-health-nr* | head -1)
export NS3_DIR NR_DIR DATA JOBS NS3 NR
jobs=()
add() { [ -f "$1_summary.csv" ] || jobs+=("$2 --out=$1"); }   # skip runs that already finished
run_jobs() {
  echo "${#jobs[@]} runs to do"
  printf '%s\n' "${jobs[@]}" | xargs -r -P "$JOBS" -I{} bash -c '{} > /dev/null 2>&1 || echo "FAILED: {}"'
}

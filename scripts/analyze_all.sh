#!/usr/bin/env bash
# Per-run metrics and paper tables/figures from the traces in $DATA.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd); source "$HERE/scripts/env.sh"
A=$HERE/analysis; OUT=$HERE/out; mkdir -p "$OUT"
for d in main_iga abstraction_matched full_nr terminal_hga terminal_handheld cr_abl cr_mask; do
  [ -d "$DATA/$d" ] && python3 "$A/analyze.py" "$DATA/$d"
done
python3 "$A/plots.py"          "$DATA/main_iga" "$OUT/main"
python3 "$A/energy_tables.py"  "$DATA/main_iga" "$DATA/full_nr" "$OUT/energy"
python3 "$A/c3_deadline.py"    "$DATA/main_iga" "$OUT/c3" main
python3 "$A/compare_nr.py"     "$DATA/full_nr" "$DATA/abstraction_matched" "$OUT/nr"
python3 "$A/terminal_sweep.py" "$DATA/terminal_handheld" "$DATA/main_iga" "$DATA/terminal_hga" "$OUT/terminal"
for w in jam dos nrjam; do python3 "$A/cr_analysis.py" $w > "$OUT/sens_$w.txt"; done
SAGIN_FIGS=$OUT/figs python3 "$A/paper_figs.py"
echo "outputs in $OUT"

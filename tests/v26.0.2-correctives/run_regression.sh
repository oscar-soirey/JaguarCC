#!/usr/bin/env bash
set -u
CCOMP="/mnt/data/jcc_fixed.py"
OUT="/mnt/data/jaguar_tests/out"
mkdir -p "$OUT"
files=(docs_full_81 advanced_structural signal_and_const class_collections reflection)
status=0
for mode in normal c89; do
  for name in "${files[@]}"; do
    src="/mnt/data/jaguar_tests/${name}.ja"
    c="$OUT/${name}_${mode}.c"
    exe="$OUT/${name}_${mode}"
    args=()
    [[ "$mode" == c89 ]] && args+=(--c89)
    echo "== $name [$mode] =="
    if ! python3 "$CCOMP" "$src" --emit-c "${args[@]}" > "$c" 2> "$OUT/${name}_${mode}.jcc.err"; then
      echo "JCC FAIL"; cat "$OUT/${name}_${mode}.jcc.err"; status=1; continue
    fi
    if ! gcc -std=c89 -pedantic -Werror -w "$c" -lm -o "$exe" > "$OUT/${name}_${mode}.gcc.out" 2> "$OUT/${name}_${mode}.gcc.err"; then
      echo "GCC FAIL"; cat "$OUT/${name}_${mode}.gcc.err"; status=1; continue
    fi
    if ! "$exe" > "$OUT/${name}_${mode}.run" 2> "$OUT/${name}_${mode}.run.err"; then
      echo "RUN FAIL"; cat "$OUT/${name}_${mode}.run.err"; status=1; continue
    fi
    echo "PASS"
    cat "$OUT/${name}_${mode}.run"
  done
done
exit $status
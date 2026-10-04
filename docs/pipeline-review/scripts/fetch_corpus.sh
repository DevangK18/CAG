#!/bin/bash
# Download the review corpus (PDFs + current chunk outputs) into data/review_corpus/.
# Uses curl with an access token because `gcloud storage cp` stalls on macOS.
# Usage: docs/pipeline-review/scripts/fetch_corpus.sh [OUT_DIR]
set -euo pipefail
BUCKET=cag-data-443e4a28
OUT=${1:-data/review_corpus}
mkdir -p "$OUT/pdfs" "$OUT/chunks" "$OUT/gpuchunks"
TOKEN=$(gcloud auth print-access-token)

fetch() {  # gs path, local file
  local obj=${1#gs://$BUCKET/}
  [ -s "$2" ] && return 0
  curl -sf -H "Authorization: Bearer $TOKEN" -o "$2" \
    "https://storage.googleapis.com/storage/v1/b/$BUCKET/o/$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$obj")?alt=media"
}

for tier in union state local_body; do
  for f in $(gcloud storage ls "gs://$BUCKET/processed/$tier/" | grep -E '_(chunks|overview)\.json$'); do
    fetch "$f" "$OUT/chunks/$(basename "$f")"
  done
done
for f in $(gcloud storage ls "gs://$BUCKET/gpu-test/processed/union/" | grep -E '\.json$'); do
  fetch "$f" "$OUT/gpuchunks/$(basename "$f")"
done
# PDFs for every report that has output (state/local PDFs may sit under raw/union/)
for c in "$OUT"/chunks/*_chunks.json; do
  rid=$(basename "$c" _chunks.json)
  [ -s "$OUT/pdfs/$rid.pdf" ] && continue
  for tier in union state local_body; do
    if fetch "gs://$BUCKET/raw/$tier/$rid.pdf" "$OUT/pdfs/$rid.pdf" 2>/dev/null; then break; fi
    rm -f "$OUT/pdfs/$rid.pdf"
  done
done
echo "chunks: $(ls "$OUT"/chunks/*_chunks.json | wc -l)  pdfs: $(ls "$OUT"/pdfs/*.pdf | wc -l)"

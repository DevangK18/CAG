"""Inspect total_amount_inr magnitudes."""
import json
from pathlib import Path

processed_dir = Path("data/processed")
files = list(processed_dir.glob("**/*_enriched.json")) or list(processed_dir.glob("**/*_chunks.json"))
print(f"Found {len(files)} files")

samples = []
for f in files[:5]:
    with open(f) as fp: data = json.load(fp)
    for finding in (data.get("semantic_enrichment", {}).get("findings", []) or [])[:5]:
        amt = finding.get("total_amount_inr")
        if amt:
            samples.append((f.name, finding.get("finding_type",""), amt))

for fname, ftype, inr in samples:
    print(f"\n{fname[:50]}  [{ftype}]")
    print(f"  total_amount_inr = {inr}")
    print(f"  /1e7 (if rupees): {inr/1e7:.4f} crore")
    print(f"  /1e9 (if paise):  {inr/1e9:.4f} crore")
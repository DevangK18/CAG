import sys, json, glob, os, re
sys.path.insert(0, '/Users/dev/Projects/CAG')
import fitz
from collections import Counter, defaultdict
from scripts.evaluation.preflight_check import words, numbers, recall, chunk_pages
from src.parsing_pipeline.extractors.text_repair import repair_font_shift
A = '/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad/audit/'
targets = sys.argv[1:]
out = {}
for f in sorted(glob.glob(A + 'gcs/processed/*/*_chunks.json')) + glob.glob(A + 'gcs/gpu-test/processed/union/*_chunks.json'):
    rid = os.path.basename(f)[:-12]; tag = ('GPU:' if 'gpu-test' in f else '') + rid[:10]
    if targets and not any(tag.startswith(t) for t in targets): continue
    d = json.load(open(f)); C = d['child_chunks']
    doc = fitz.open(A + 'pdfs/' + rid + '.pdf')
    pt = [repair_font_shift(p.get_text('text')) for p in doc]
    by = defaultdict(str)
    for c in C:
        for p in chunk_pages(c): by[p] += ' ' + (c.get('content') or '')
    rows = []
    for i, t in enumerate(pt):
        ew, en = words(t), numbers(t)
        if sum(ew.values()) < 30: continue
        near = ' '.join(by.get(p, '') for p in (i - 1, i, i + 1))
        gw, gn = words(near), numbers(near)
        wr, nr = recall(ew, gw), recall(en, gn)
        if wr < 0.85 or (sum(en.values()) >= 5 and nr < 0.7):
            miss_n = [n for n, k in en.items() if gn[n] < k][:8]
            miss_w = [w for w, k in ew.most_common() if gw[w] < k][:10]
            rows.append({'page': i, 'word_recall': round(wr, 2), 'num_recall': round(nr, 2), 'n_nums': sum(en.values()),
                         'chunks_on_page': sum(1 for c in C if i in chunk_pages(c)), 'missing_nums': miss_n, 'missing_words': miss_w})
    out[tag] = rows
    print(tag, 'pages flagged', len(rows), [ (r['page'], r['word_recall'], r['num_recall']) for r in rows][:40])
json.dump(out, open(A + 'page_recall_' + ('_'.join(targets) or 'all') + '.json', 'w'), indent=1)

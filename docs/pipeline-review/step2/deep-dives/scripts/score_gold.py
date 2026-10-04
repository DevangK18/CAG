"""Score Phase 9 findings/recommendations against gold labels.

Usage (repo root, after scripts/fetch_corpus.sh): PYTHONPATH=. python docs/pipeline-review/step2/deep-dives/scripts/score_gold.py [REPORT_PREFIX ...]
Writes docs/pipeline-review/step2/deep-dives/gold_scores.json and prints a summary.
Matching: pipeline item p matches gold item g if |page diff|<=2 and they share >=3 word 5-gram
shingles or p contains g's first 10 anchor words.
"""
import json, re, sys, glob, os, collections
from src.parsing_pipeline.modules.enrichment.finding_extractor import FindingExtractor
from src.parsing_pipeline.modules.enrichment.recommendation_extractor import RecommendationExtractor

A = os.environ.get('REVIEW_CORPUS', 'data/review_corpus')  # fill with docs/pipeline-review/scripts/fetch_corpus.sh
G = 'docs/pipeline-review/gold-labels'
OUT = 'docs/pipeline-review/step2/deep-dives/gold_scores.json'
SOURCES = {  # which pipeline output to score (post-fix where available)
    '2025_08': A + '/gpuchunks',
    '2025_38': A + '/chunks', 'OD_2025_05': A + '/chunks', 'JH_2025_02': A + '/chunks',
    'BR_2024_03': A + '/chunks', 'HP_2022': A + '/chunks',
}

def words(s): return re.findall(r'[a-z0-9]+', (s or '').lower())
def shingles(s, n=5):
    w = words(s); return {' '.join(w[i:i+n]) for i in range(len(w)-n+1)}
def match(p_text, p_page, g):
    if abs((p_page or 0) - g['page']) > 2: return False
    a = ' '.join(words(g['anchor'])[:10]); pt = ' '.join(words(p_text))
    if len(a) > 20 and a in pt: return True
    return len(shingles(p_text) & g['_sh']) >= 3

def load_pipeline(prefix):
    f = glob.glob(f"{SOURCES[prefix]}/**/{prefix}*_chunks.json", recursive=True) or glob.glob(f"{SOURCES[prefix]}/{prefix}*_chunks.json")
    return json.load(open(f[0])), f[0]

def acceptance_rule(fx, text, tier):
    m = fx._semantic_matcher.match_patterns(text)
    conf = fx._semantic_matcher.calculate_finding_confidence(text, m, fx._current_report_type)
    ft = fx._detect_finding_type(text, tier)
    mon = fx._monetary_processor.extract_monetary_values_with_preference(text)
    ind = any(p.search(text) for p in fx._finding_indicators)
    if conf >= fx.finding_confidence_threshold: return 'R1_confidence'
    if mon and (ft.value != 'other' or ind): return 'R2_money+type/indicator'
    if ft.value != 'other' and ind: return 'R3_type+indicator'
    return 'none'

def why_not(fx, chunk, tier):
    if chunk is None: return 'text_not_in_any_chunk'
    ct = chunk.get('content_type')
    if ct not in ('paragraph', 'list'): return f'content_type={ct}'
    c = chunk.get('content', '')
    if len(c) < 50: return 'chunk<50chars'
    if fx._is_non_finding(c):
        for p in fx.NON_FINDING_PATTERNS:
            if p.search(c[:300]): return 'NON_FINDING:' + p.pattern[:45]
    r = acceptance_rule(fx, c, tier)
    return 'not_accepted' if r == 'none' else f'accepted_by_{r}_then_removed(LLM?)'

def find_chunk(children, g):
    a = ' '.join(words(g['anchor'])[:8]); best = None
    for c in children:
        if abs((c.get('source_page_physical') or 0) - g['page']) > 2: continue
        ct = ' '.join(words(c.get('content')))
        if a and a in ct: return c
        if len(shingles(c.get('content')) & g['_sh']) >= 3: best = best or c
    return best

def score(prefix):
    gold = json.load(open(f'{G}/{prefix}.json'))
    d, path = load_pipeline(prefix)
    tier = d['report_metadata'].get('government_body_type') or 'union'
    se = d.get('semantic_enrichment') or {}
    PF, PR = se.get('findings') or [], se.get('recommendations') or []
    GF, GR = gold['findings'], gold['recommendations']
    for g in GF + GR: g['_sh'] = shingles(g['text'])
    from src.parsing_pipeline.modules import report_type_profiles as rtp
    fx = FindingExtractor(); fx.set_report_type(rtp.normalize_report_type(d['report_metadata'].get('report_type') or 'general'))
    children = d['child_chunks']
    res = {'report': prefix, 'pipeline_file': os.path.basename(path), 'tier': tier}

    # ---- findings
    pf_match = []
    for p in PF:
        mg = [g for g in GF if match(p['text'], p.get('page'), g)]
        mr = [g for g in GR if match(p['text'], p.get('page'), g)]
        pf_match.append((p, mg, mr))
    tp_any = sum(1 for _, mg, _ in pf_match if mg)
    tp_strict = sum(1 for _, mg, _ in pf_match if any(not g['borderline'] for g in mg))
    is_rec = sum(1 for _, mg, mr in pf_match if not mg and mr)
    gf_core = [g for g in GF if not g['borderline']]
    covered = lambda g: any(match(p['text'], p.get('page'), g) for p in PF)
    rec_core = [g for g in gf_core if covered(g)]
    by_loc = collections.defaultdict(lambda: [0, 0])
    for g in gf_core:
        by_loc[g['location']][1] += 1; by_loc[g['location']][0] += covered(g)
    # strata
    strata = collections.defaultdict(lambda: [0, 0])
    rules = collections.defaultdict(lambda: [0, 0])
    patt = collections.defaultdict(lambda: [0, 0])
    for p, mg, _ in pf_match:
        c = p.get('confidence', 0); s = '<0.5' if c < .5 else ('0.5-0.7' if c < .7 else '>=0.7')
        strata[s][1] += 1; strata[s][0] += bool(mg)
        r = acceptance_rule(fx, p['text'], tier); rules[r][1] += 1; rules[r][0] += bool(mg)
        for t in set(p.get('pattern_types') or ['(none)']): patt[t][1] += 1; patt[t][0] += bool(mg)
    # recall loss reasons
    loss = collections.Counter(); loss_ex = []
    for g in gf_core:
        if covered(g): continue
        ch = find_chunk(children, g); w = why_not(fx, ch, tier); key = w.split(':')[0] if not w.startswith('NON') else w
        loss[key] += 1
        if len(loss_ex) < 40: loss_ex.append((g['id'], g['page'], w, g['anchor'][:80]))
    # LLM-rejected: re-run extractor without LLM, candidates absent from output
    cands = fx.extract_findings(d['report_metadata']['report_id'], children, tier, d['parent_chunks'])
    out_chunks = {p.get('source_chunk_id') for p in PF}
    rejected = [c for c in cands if c.source_chunk_id not in out_chunks]
    rej_real = [c for c in rejected if any(match(c.text, c.page, g) for g in GF)]
    # false-positive categories
    fp_cat = collections.Counter(); fp_ex = []
    for p, mg, mr in pf_match:
        if mg or mr: continue
        t = p['text']
        cat = ('mgmt_reply' if re.search(r'\b(stated|replied|informed|assured|accepted)\b.{0,40}\(?(19|20)\d\d|\breply\b', t, re.I) else
               'exec_summary_flagged' if p.get('is_executive_summary') else
               'background/other')
        fp_cat[cat] += 1
        if len(fp_ex) < 25: fp_ex.append((p['finding_id'][-3:], p.get('page'), round(p.get('confidence', 0), 2), cat, t[:110]))
    res['findings'] = dict(
        pipeline=len(PF), gold=len(GF), gold_core=len(gf_core),
        precision_any=round(tp_any / len(PF), 3) if PF else None,
        precision_strict=round(tp_strict / len(PF), 3) if PF else None,
        pipeline_matching_a_recommendation=is_rec,
        recall_core=round(len(rec_core) / len(gf_core), 3) if gf_core else None,
        recall_by_location={k: f'{a}/{b}' for k, (a, b) in by_loc.items()},
        precision_by_confidence={k: f'{a}/{b}' for k, (a, b) in strata.items()},
        precision_by_acceptance_rule={k: f'{a}/{b}' for k, (a, b) in rules.items()},
        precision_by_pattern={k: f'{a}/{b}' for k, (a, b) in sorted(patt.items(), key=lambda x: -x[1][1])},
        recall_loss_reasons=dict(loss.most_common()), recall_loss_examples=loss_ex,
        llm_rejected_candidates=len(rejected), llm_rejected_that_were_real=len(rej_real),
        llm_rejected_real_examples=[(c.page, c.text[:100]) for c in rej_real[:8]],
        false_positive_categories=dict(fp_cat), false_positive_examples=fp_ex,
    )
    # ---- amounts on matched pairs (non-borderline gold with impact)
    am = collections.Counter()
    for p, mg, _ in pf_match:
        g = next((g for g in mg if g.get('impact_amount')), None)
        if not g: continue
        gc = g['impact_amount']['crore']; am['pairs'] += 1
        mx = p.get('monetary_value_crore'); tot = (p.get('total_amount_inr') or 0) / 1e9
        am['max_equals_gold'] += bool(mx and abs(mx - gc) <= max(0.011, 0.01 * gc))
        am['sum_equals_gold'] += bool(tot and abs(tot - gc) <= max(0.011, 0.01 * gc))
        am['sum_gt_1.5x_gold'] += bool(tot > 1.5 * gc)
        from src.parsing_pipeline.modules.enrichment.monetary_processor import MonetaryProcessor
        pr = MonetaryProcessor().get_primary_amount(p['text'])
        am['identify_primary_equals_gold'] += bool(pr and abs(pr.value.normalized_inr / 1e9 - gc) <= max(0.011, 0.01 * gc))
    res['amounts'] = dict(am)
    # ---- recommendations
    pr_match = [(r, [g for g in GR if match(r['text'], r.get('page'), g)]) for r in PR]
    # duplicates (chapter copies of exec-summary recs) are scored via their original
    gr_core = [g for g in GR if not g['borderline'] and not g.get('duplicate_of')]
    by_id = {g['id']: g for g in GR}
    strat = collections.defaultdict(lambda: [0, 0])
    for r, mg in pr_match:
        s = r.get('extraction_strategy'); strat[s][1] += 1; strat[s][0] += bool(mg)
    hit = lambda g: any(match(r['text'], r.get('page'), g) for r in PR)
    dups = {}
    for g in GR:
        if g.get('duplicate_of'): dups.setdefault(g['duplicate_of'], []).append(g)
    rcov = [g for g in gr_core if hit(g) or any(hit(x) for x in dups.get(g['id'], []))]
    by_form = collections.defaultdict(lambda: [0, 0])
    for g in gr_core:
        by_form[g['form']][1] += 1; by_form[g['form']][0] += g in rcov
    # dup: gold recs matched by >1 pipeline rec
    res['recommendations'] = dict(
        pipeline=len(PR), gold=len(GR), gold_core=len(gr_core),
        precision=round(sum(1 for _, m in pr_match if m) / len(PR), 3) if PR else None,
        recall_core=round(len(rcov) / len(gr_core), 3) if gr_core else None,
        precision_by_strategy={k: f'{a}/{b}' for k, (a, b) in strat.items()},
        recall_by_form={k: f'{a}/{b}' for k, (a, b) in by_form.items()},
        false_positive_examples=[(r.get('page'), r.get('extraction_strategy'), r['text'][:110]) for r, m in pr_match if not m][:15],
        missed_examples=[(g['id'], g['page'], g['form'], g['anchor'][:90]) for g in gr_core if g not in rcov][:15],
    )
    return res

if __name__ == '__main__':
    prefixes = sys.argv[1:] or [p for p in SOURCES if os.path.exists(f'{G}/{p}.json')]
    allres = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for p in prefixes:
        allres[p] = score(p)
        f, r = allres[p]['findings'], allres[p]['recommendations']
        print(f"{p:11} F: pipe {f['pipeline']:4} gold {f['gold_core']:4} P {f['precision_any']} (strict {f['precision_strict']}) R {f['recall_core']}   "
              f"Recs: pipe {r['pipeline']} gold {r['gold_core']} P {r['precision']} R {r['recall_core']}")
    json.dump(allres, open(OUT, 'w'), indent=1, ensure_ascii=False, default=str)

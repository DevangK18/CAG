"""Structural + Phase 8/9 metrics for every chunks JSON."""
import json, glob, re, os, statistics as st, sys
from collections import Counter, defaultdict
A = '/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad/audit'
files = sorted(glob.glob(A + '/gcs/processed/*/*_chunks.json')) + sorted(glob.glob(A + '/gcs/gpu-test/processed/union/*_chunks.json'))

def short(rid, path):
    s = rid[:10] if rid[0].isdigit() else rid[:10]
    return ('GPU:' if 'gpu-test' in path else '') + s

def empty(v):
    return v is None or v == '' or v == [] or v == {}

def flat(d, prefix=''):
    for k, v in d.items():
        if isinstance(v, dict) and v and k in ('metadata', 'source', 'location', 'extraction', 'hierarchy_meta'):
            yield from flat(v, prefix + k + '.')
        else:
            yield prefix + k, v

out = {}
for f in files:
    d = json.load(open(f))
    rm = d['report_metadata']; rid = rm['report_id']; key = short(rid, f)
    P, C = d['parent_chunks'], d['child_chunks']
    pids = {p['chunk_id'] for p in P}
    m = {'file': os.path.relpath(f, A), 'tier': rm.get('government_body_type'), 'parents': len(P), 'children': len(C)}
    # dup ids
    m['dup_parent_ids'] = len(P) - len(pids)
    cids = [c['chunk_id'] for c in C]; m['dup_child_ids'] = len(cids) - len(set(cids))
    # orphan / empty parents
    per_parent = Counter(c.get('parent_chunk_id') for c in C)
    m['orphan_children'] = sum(n for p, n in per_parent.items() if p not in pids)
    m['parents_without_children'] = sum(1 for p in pids if per_parent[p] == 0)
    cpp = [per_parent[p] for p in pids]
    m['children_per_parent_median'] = st.median(cpp) if cpp else 0
    m['parents_with_1_child'] = sum(1 for n in cpp if n == 1)
    m['parents_with_le2_children_pct'] = round(100 * sum(1 for n in cpp if n <= 2) / len(cpp), 1) if cpp else 0
    m['toc_level_dist'] = dict(Counter(p.get('toc_level') for p in P))
    types = Counter(c.get('content_type') for c in C); m['content_types'] = dict(types)
    lens = [len(c.get('content') or '') for c in C]
    m['child_len_median'] = st.median(lens) if lens else 0
    m['tiny_children_lt40'] = sum(1 for c in C if len((c.get('content') or '').strip()) < 40 and c.get('content_type') != 'header')
    m['empty_children'] = sum(1 for c in C if not (c.get('content') or '').strip())
    m['max_child_len'] = max(lens) if lens else 0
    m['header_children'] = types.get('header', 0)
    # exact duplicate contents (non-trivial)
    norm = Counter(re.sub(r'\s+', ' ', (c.get('content') or '').strip().lower()) for c in C if len((c.get('content') or '')) >= 80)
    m['dup_content_chunks'] = sum(n - 1 for n in norm.values() if n > 1)
    # metadata consistency
    for fld in ('audit_category', 'government_body_type', 'state_name', 'report_year'):
        cv = Counter(str(c.get(fld)) for c in C); pv = Counter(str(p.get(fld)) for p in P if fld in p)
        m[f'meta_{fld}'] = {'report': rm.get(fld), 'children': dict(cv), 'parents': dict(pv)}
    m['report_metadata'] = {k: rm.get(k) for k in rm if k not in ('report_id', 'report_title', 'source_url', 'source_filename')}
    # field emptiness
    child_empty = Counter(); child_seen = Counter()
    for c in C:
        for k, v in flat(c):
            child_seen[k] += 1; child_empty[k] += empty(v)
    m['child_fields_always_empty'] = sorted(k for k in child_seen if child_empty[k] == child_seen[k])
    par_empty = Counter(); par_seen = Counter()
    for p in P:
        for k, v in p.items():
            par_seen[k] += 1; par_empty[k] += empty(v)
    m['parent_fields_always_empty'] = sorted(k for k in par_seen if par_empty[k] == par_seen[k])
    # page checks
    pages = [c.get('source_page_physical') for c in C]
    m['child_page_none'] = sum(1 for p in pages if p is None)
    m['logical_page_types'] = dict(Counter(type(c.get('source_page_logical')).__name__ for c in C))
    pmap = {p['chunk_id']: p for p in P}
    outside = 0
    for c in C:
        p = pmap.get(c.get('parent_chunk_id'))
        if p and p.get('page_range_physical') and c.get('source_page_physical') is not None:
            a, b = p['page_range_physical']
            if not (a <= c['source_page_physical'] <= b): outside += 1
    m['children_outside_parent_pages'] = outside
    # parent ranges overlap / inverted
    m['parent_inverted_ranges'] = sum(1 for p in P if p.get('page_range_physical') and p['page_range_physical'][0] > p['page_range_physical'][1])
    m['parent_content_summary_filled'] = sum(1 for p in P if p.get('content_summary'))
    # processing stats
    ps = d.get('processing_stats') or {}
    m['ps_processing_status'] = ps.get('processing_status'); m['ps_errors'] = ps.get('errors_encountered')
    m['ps_counts_match'] = (ps.get('total_parent_chunks') == len(P), ps.get('total_child_chunks') == len(C), ps.get('content_type_distribution') == dict(types))
    dlq = ps.get('dlq_entries') or []
    m['dlq_total'] = len(dlq); m['dlq_reasons'] = dict(Counter(e.get('reason') for e in dlq if isinstance(e, dict)))
    m['dlq_section_ids'] = dict(Counter((e.get('context') or {}).get('section_id') for e in dlq if isinstance(e, dict)))
    m['page_coverage'] = ps.get('page_coverage'); m['phase_10b_complete'] = ps.get('phase_10b_complete')
    m['ps_keys'] = sorted(ps)
    # visual registry
    va = d.get('visual_asset_registry') or {}
    m['va_tables'] = va.get('total_tables'); m['va_figures'] = va.get('total_figures'); m['va_extraction_stats'] = va.get('extraction_stats')
    m['table_children'] = types.get('table_markdown', 0); m['image_children'] = types.get('image_caption', 0)
    figs = va.get('figures') or []
    if figs:
        m['figure_keys'] = sorted(figs[0].keys())
        m['figures_with_chart_data'] = sum(1 for g in figs if g.get('chart_data') or g.get('extracted_data') or g.get('data'))
    tabs = va.get('tables') or []
    if tabs: m['table_keys'] = sorted(tabs[0].keys())
    # image caption chunk content
    caps = [c for c in C if c.get('content_type') == 'image_caption']
    m['image_caption_generic'] = sum(1 for c in caps if len((c.get('content') or '')) < 30)
    m['image_caption_with_sd'] = sum(1 for c in caps if c.get('structured_data'))
    # footnotes
    m['footnote_index'] = len(d.get('footnote_index') or {})
    # semantic enrichment
    se = d.get('semantic_enrichment') or {}
    F = se.get('findings') or []; R = se.get('recommendations') or []
    m['findings'] = len(F)
    m['finding_types'] = dict(Counter(x.get('finding_type') for x in F))
    m['finding_other_pct'] = round(100 * m['finding_types'].get('other', 0) / len(F), 1) if F else None
    m['finding_severity'] = dict(Counter(x.get('severity') for x in F))
    m['findings_with_evidence'] = sum(1 for x in F if x.get('evidence_links'))
    m['findings_with_money'] = sum(1 for x in F if x.get('monetary_values'))
    m['findings_dup'] = sum(1 for x in F if x.get('is_duplicate'))
    m['findings_exec'] = sum(1 for x in F if x.get('is_executive_summary'))
    m['findings_no_chunk'] = sum(1 for x in F if x.get('source_chunk_id') not in set(cids))
    m['findings_chapter_none'] = sum(1 for x in F if not x.get('chapter'))
    m['recs'] = len(R)
    m['rec_strategies'] = dict(Counter(x.get('extraction_strategy') for x in R))
    m['rec_number_set'] = sum(1 for x in R if x.get('rec_number') is not None)
    m['rec_numbered_text_but_null'] = sum(1 for x in R if x.get('rec_number') is None and re.match(r'^\s*(\(?\d+[\.\)]|\(?[ivx]+\)|Recommendation\s*\d)', x.get('text') or '', re.I))
    rt = Counter(re.sub(r'^\W*\d+[\.\)]\s*', '', (x.get('text') or '')).strip().lower()[:120] for x in R)
    m['rec_dup_text'] = sum(n - 1 for n in rt.values() if n > 1)
    m['rec_with_related_findings'] = sum(1 for x in R if x.get('related_finding_ids'))
    m['rec_with_para_citations'] = sum(1 for x in R if x.get('paragraph_citations'))
    m['rec_status'] = dict(Counter(x.get('status') for x in R))
    sc = se.get('section_classifications') or []
    m['section_types'] = dict(Counter(x.get('section_type') for x in sc))
    m['section_other_pct'] = round(100 * m['section_types'].get('other', 0) / len(sc), 1) if sc else None
    m['section_conf0'] = sum(1 for x in sc if not x.get('confidence'))
    xr = se.get('cross_references') or []
    m['xref_total'] = len(xr); m['xref_resolved'] = sum(1 for x in xr if x.get('resolved'))
    m['xref_by_type'] = {t: [sum(1 for x in xr if x.get('reference_type') == t), sum(1 for x in xr if x.get('reference_type') == t and x.get('resolved'))] for t in set(x.get('reference_type') for x in xr)}
    al = se.get('annexure_links') or []
    m['annex_total'] = len(al); m['annex_resolved'] = sum(1 for x in al if x.get('resolved'))
    esi = se.get('executive_summary_index') or {}
    items = esi.get('items') or []
    m['esi_items'] = len(items); m['esi_with_citations'] = sum(1 for x in items if x.get('paragraph_citations')); m['esi_resolved'] = sum(1 for x in items if x.get('resolved_chunk_ids'))
    m['esi_item_types'] = dict(Counter(x.get('item_type') for x in items)); m['esi_keys'] = sorted(esi)
    m['esi_page_range'] = esi.get('page_range')
    m['box_elements'] = len(se.get('box_elements') or [])
    ent = se.get('entities') or {}
    m['entities'] = {k: len(v) if hasattr(v, '__len__') else v for k, v in ent.items()}
    tc = se.get('temporal_coverage') or {}
    m['audit_period'] = tc.get('audit_period'); m['previous_audit_refs'] = tc.get('previous_audit_refs')
    stt = (se.get('statistics') or {})
    m['stat_total_crore'] = (stt.get('findings') or {}).get('total_monetary_crore')
    m['stat_detected_report_type'] = (stt.get('report_info') or {}).get('detected_report_type')
    m['se_keys'] = sorted(se)
    out[key] = m
    print(key, 'done', file=sys.stderr)
json.dump(out, open(A + '/metrics_structural.json', 'w'), indent=1, ensure_ascii=False, default=str)

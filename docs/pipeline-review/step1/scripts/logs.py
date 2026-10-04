import re, sys, json
from collections import Counter, defaultdict
A='/private/tmp/claude-501/-Users-dev-Projects-CAG/5b128fa5-8434-46e2-a3c3-a9695a9cdf81/scratchpad/audit/gcs/'
runs={'union':'runs/35994256570/pipeline.log','state':'runs/36167161942/pipeline.log','local':'runs/36191270703/pipeline.log','gpu':'runs-gpu/36194014772/pipeline.log'}
LINE=re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \| ([^|]+) \| (\w+) \| (.*)$')
def norm(msg):
    msg=re.sub(r'\[[A-Z]{0,2}_?\d{4}_[^\]]*\]','[RID]',msg)
    msg=re.sub(r'\b(?:[A-Z]{2}_)?\d{4}_\d+_\w+','RID',msg)
    msg=re.sub(r'\d+(\.\d+)?','N',msg)
    return msg[:160]
res={}
for name,path in runs.items():
    lv=Counter(); tmpl=defaultdict(Counter)
    phases=[]; cur=None
    for line in open(A+path,errors='replace'):
        line=line.rstrip('\n')
        if re.match(r'^PHASE [\d\.a-z]+', line): phases.append(line[:60])
        m=LINE.match(line)
        if m:
            ts,mod,lvl,msg=m.groups()
            lv[lvl]+=1
            if lvl in('WARNING','ERROR','CRITICAL'):
                tmpl[lvl][(mod.strip().split('.')[-1], norm(msg))]+=1
    res[name]={'levels':dict(lv),'phases':phases}
    print('=========',name,dict(lv))
    for l in ('ERROR','WARNING'):
        print('--',l, sum(tmpl[l].values()))
        for (mod,t),n in tmpl[l].most_common(45): print(f'{n:5d} {mod[:28]:28s} {t}')

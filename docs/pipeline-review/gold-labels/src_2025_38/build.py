import json,re,sys,os
D=os.path.dirname(os.path.abspath(__file__))
def norm(s): return re.sub(r'\s+',' ',s).strip()
PAGES=[norm(open(f"{D}/p{i:03d}.txt").read()) for i in range(90)]
FIND=[];RECS=[];errs=[]
def span(page,start,end):
    t=PAGES[page]; i=t.find(start)
    if i<0: errs.append(f"p{page} start not found: {start[:50]}"); return start
    j=t.find(end,i) if end else -1
    if end and j<0:
        # allow continuation on next page
        t2=t+' '+PAGES[page+1]; j=t2.find(end,i)
        if j<0: errs.append(f"p{page} end not found: {end[:50]}"); return t[i:i+300]
        return t2[i:j+len(end)]
    return t[i:j+len(end)] if end else t[i:i+400]
def F(page,start,end,loc,summary,ftype,impact=None,other=(),para=None,printed=None,borderline=False,note=""):
    txt=span(page,start,end)
    FIND.append(dict(id=f"F{len(FIND)+1:03d}",page=page,printed_page=printed,para_no=para,location=loc,
        anchor=" ".join(start.split()[:18]),text=txt,summary=summary,finding_type=ftype,
        impact_amount=(dict(raw=impact[0],crore=impact[1]) if impact else None),other_amounts=list(other),borderline=borderline,note=note))
def R(page,start,end,loc,num,addressee,form,dup=None,printed=None,borderline=False,note=""):
    txt=span(page,start,end)
    RECS.append(dict(id=f"R{len(RECS)+1:03d}",page=page,printed_page=printed,rec_number=num,location=loc,
        anchor=" ".join(start.split()[:18]),text=txt,addressee=addressee,form=form,duplicate_of=dup,borderline=borderline,note=note))
exec(open(f"{D}/labels.py").read())
out=dict(report_id="2025_38_Performance_Audit_of_Blast_Furnace_in_Steel_Authority_of_India_Limited",labeller="main-session",
  pages_total=90,pages_read=PAGES_READ,unreadable_pages=UNREADABLE,findings=FIND,recommendations=RECS,labelling_notes=NOTES)
json.dump(out,open("/Users/dev/Projects/CAG/docs/pipeline-review/gold-labels/2025_38.json","w"),indent=1,ensure_ascii=False)
print(len(FIND),"findings",len(RECS),"recs"); print("\n".join(errs) or "anchors ok")

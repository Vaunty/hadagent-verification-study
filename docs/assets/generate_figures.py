"""Rebuild the evidence figures and proposed-study diagram.

Requires matplotlib. Does not call a model, endpoint, or external service.
SVG keeps editable text; PNG is the GitHub README fallback.
"""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

HERE = Path(__file__).resolve().parent
D = json.loads((HERE / 'figure_data.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans', 'svg.fonttype':'none',
                     'font.size':12, 'axes.unicode_minus':False})
BG='#f5f7fb'; INK='#14243b'; MUTED='#526279'; TEAL='#087f8c'
BLUE='#3266a8'; AMBER='#b7600d'; LINE='#d4dfeb'; WHITE='#ffffff'

def canvas(title, sub, tag):
    f=plt.figure(figsize=(16,9), facecolor=BG)
    a=f.add_axes([0,0,1,1]); a.set(xlim=(0,16), ylim=(0,9)); a.axis('off')
    a.text(.6,8.52,tag.upper(),color=TEAL,fontsize=11,weight='bold',va='top')
    a.text(.6,8.05,title,color=INK,fontsize=27,weight='bold',va='top')
    a.text(.6,7.45,sub,color=MUTED,fontsize=13,va='top',linespacing=1.5)
    return f,a

def box(a,x,y,w,h,title,body='',color=BLUE,face=WHITE,headsize=16,bodysize=12):
    a.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.02,rounding_size=0.12',
                             ec=LINE,fc=face,lw=1.2))
    a.add_patch(Rectangle((x+.18,y+h-.31),.48,.055,color=color,lw=0))
    a.text(x+.2,y+h-.48,title,fontsize=headsize,color=INK,weight='bold',va='top',linespacing=1.3)
    if body:a.text(x+.2,y+h-.48-.38*(title.count('\n')+1),body,
                   fontsize=bodysize,color=MUTED,va='top',linespacing=1.5)

def arrow(a,start,end,color=BLUE,style='-',rad=0):
    a.add_patch(FancyArrowPatch(start,end,arrowstyle='-|>',mutation_scale=18,
                color=color,lw=2,linestyle=style,connectionstyle=f'arc3,rad={rad}'))

def footer(a,text):
    a.plot([.6,15.4],[.82,.82],color=LINE,lw=1)
    a.text(.6,.6,text,fontsize=10,color=MUTED,va='top',linespacing=1.5)

def save(f,name):
    for ext in ('svg','png'):
        f.savefig(HERE/f'{name}.{ext}',dpi=160,facecolor=BG,metadata={'Creator':'Matplotlib; source: generate_figures.py'})
    plt.close(f)

def boundary():
    f,a=canvas('A correct answer does not identify the model that ran',
               'The controlled local test asks whether the verifier can distinguish model execution from a known-answer lookup.',
               'HadAgent / the verification question')
    steps=[('01  A model is claimed','Signed submission\nNames a model and an endpoint'),
           ('02  The verifier asks','Benchmark questions go to\nthe supplied endpoint'),
           ('03  A lookup answers','Known labels are returned\nThe named model does not run'),
           ('04  The check passes','Original and isolated repair\nboth accept this local fixture')]
    for i,(title,body) in enumerate(steps):
        x=.6+i*3.78; box(a,x,4.65,3.45,1.85,title,body,TEAL if i==3 else BLUE,headsize=14,bodysize=11)
        if i<3:arrow(a,(x+3.47,5.55),(x+3.76,5.55))
    box(a,.6,2.35,7.1,1.7,'What this demonstrates',
        'A passing score check can coexist with no execution\nof the named model in the copied local prototype.',TEAL)
    box(a,8,2.35,7.4,1.7,'Why the distinction matters',
        'If trust or payment depends on model identity,\nthat identity needs evidence beyond correct answers.',AMBER)
    a.text(.8,1.7,'Scope: synthetic lookup participant; measured local validator decisions. No deployed network or reward system tested.',
           color=MUTED,fontsize=12,va='top')
    footer(a,'Evidence: P012 known-answer control, commit '+D['p012']['commit'][:7]+'. The score repair addresses arithmetic, not model binding.\nConceptual interpretation of a controlled test; no claim of general exploit prevalence or novelty.')
    save(f,'verification-boundary')

def score_repair():
    p=D['p012']; n=p['inflation']['cases']; old=p['inflation']['original_accepted']; new=p['inflation']['repair_accepted']
    f,a=canvas('The repair changes score acceptance, not model identity',
        'Same signed synthetic candidates, two validator arms. Counts describe one exhaustive finite test grid.',
        'P012 / what the repair did and did not change')
    a.text(.8,6.63,'BELOW-THRESHOLD SCORE-INFLATION CASES ACCEPTED',fontsize=12,color=MUTED,weight='bold')
    x0=4.2; width=9.4
    for y,label,val,col in [(5.6,'Original validator',old,AMBER),(4.6,'Isolated repair',new,TEAL)]:
        a.text(.8,y+.23,label,color=INK,fontsize=16,va='center')
        a.add_patch(Rectangle((x0,y),width,.48,fc=LINE,ec='none'))
        if val:a.add_patch(Rectangle((x0,y),width*val/n,.48,fc=col,ec='none'))
        else:a.plot([x0,x0],[y,y+.48],color=col,lw=3)
        a.text(14,y+.24,f'{val} / {n}',color=col,fontsize=20,weight='bold',va='center')
    a.text(x0,4.18,'0',fontsize=10,color=MUTED)
    a.text(x0+width,4.18,f'{n} cases',fontsize=10,color=MUTED,ha='right')
    e=p['eligible_synthetic_controls']; l=p['known_answer_lookup']
    box(a,.6,1.65,7.1,2,'Eligible synthetic controls still pass',
        f'Original {e["original_accepted"]}/{e["cases"]}    →    Repair {e["repair_accepted"]}/{e["cases"]}\nNo false rejection within these six synthetic controls.',TEAL)
    box(a,8,1.65,7.4,2,'The no-model lookup still passes',
        'Original: accepted    →    Repair: accepted\nThis all-correct lookup is one of the controls at left.',AMBER)
    footer(a,'Source: saved P012 report '+p['report_sha256'][:16]+'…; commit '+p['commit'][:7]+'. Participants and inputs simulated; decisions measured.\nThese are finite cohort counts, not population attack rates or an honest-model false-rejection estimate.')
    save(f,'score-repair')

def baseline():
    p=D['p013']; f,a=canvas('The model repeated its answers, but did not qualify',
        'One paired local run: Qwen2.5-1.5B-Instruct Q4_K_M · CPU llama.cpp b11514 · same settings, fresh processes.',
        'P013 / genuine-model baseline')
    x0=3.25; width=11.05
    a.text(x0,6.65,'SCORE UNDER THE PROTOTYPE’S NORMALIZED-PREFIX SCORER',fontsize=12,color=MUTED,weight='bold')
    for y,label,val in [(5.6,'Claim phase',p['claim_score']),(4.55,'Validation phase',p['validation_score'])]:
        a.text(.8,y+.23,label,fontsize=15,color=INK,va='center')
        a.add_patch(Rectangle((x0,y),width,.5,fc=LINE,ec='none'))
        a.add_patch(Rectangle((x0,y),width*val/p['score_scale'],.5,fc=BLUE,ec='none'))
        a.text(x0+width*val/p['score_scale']+.18,y+.25,f'{val:,} / {p["score_scale"]:,}',fontsize=15,color=INK,va='center',weight='bold')
    thresholdx=x0+width*p['threshold']/p['score_scale']
    a.plot([thresholdx,thresholdx],[4.3,6.3],ls='--',color=AMBER,lw=2)
    a.text(thresholdx,6.33,'Acceptance threshold: 8,000',ha='center',color=AMBER,fontsize=12)
    a.text(x0,4.05,'28 / 100 prefix matches in each phase. This is not standard benchmark accuracy.',fontsize=12,color=MUTED)
    box(a,.6,1.4,4.75,2,'200 model requests',
        '100 in each phase\nOne paired protocol trial',BLUE)
    box(a,5.65,1.4,4.75,2,'100 / 100 text pairs agree',
        'Parsed generated text was identical\nResponse metadata still differed',TEAL,headsize=15)
    box(a,10.7,1.4,4.7,2,'0 eligible honest trials',
        'Rejection was below-threshold\nFalse-rejection rate: undefined',AMBER,headsize=15)
    footer(a,'Source: saved P013 report '+p['report_sha256'][:16]+'…; commit '+p['commit'][:7]+'. Independent AI artifact audit, not a second model run.\nOne model, one configuration, one fixed benchmark. No estimate of cross-hardware reproducibility or a general rejection rate.')
    save(f,'honest-baseline')

def framework():
    f,a=canvas('Where this study sits inside HadAgent',
        'The paper replaces hash-based mining with useful inference. This study evaluates parts of the available prototype.',
        'Design intent / implementation / evidence')
    a.text(.8,6.65,'HADAGENT’S PROPOSED FRAMEWORK',fontsize=12,color=MUTED,weight='bold')
    a.text(7.1,6.65,'WHAT THE STUDY ACTUALLY REACHES',fontsize=12,color=MUTED,weight='bold')
    rows=[
        ('Agent requests','Prompt + model reference + decoding settings',
         'No end-to-end serving evaluation','The request names a configuration; it is not model-agnostic.',BLUE),
        ('Master recomputation and voting','Honest masters independently evaluate and agree',
         'Full consensus path not evaluated','Re-querying a prover endpoint is not independent execution.',AMBER),
        ('Proof verification','Check the submitted evaluation against its claim',
         'Directly studied: P012 and P013','Score arithmetic, endpoint responses, and a real-model baseline.',TEAL),
        ('Blocks and ledger','Signed records, per-lane Merkle roots, chain linkage',
         'Local block / append checks','Local acceptance does not establish network agreement.',TEAL),
        ('Agentic harness and trust tiers','Monitor nodes; promote, demote, or exclude them',
         'Separate synthetic simulation only','Copied podl_chain lacks the full advertised trust pipeline.',AMBER),
    ]
    for i,(t,b,rt,rb,c) in enumerate(rows):
        y=5.5-i*.91
        a.add_patch(FancyBboxPatch((.6,y),14.8,.75,boxstyle='round,pad=.02,rounding_size=.08',fc=WHITE,ec=LINE,lw=1))
        a.add_patch(Rectangle((.6,y),.055,.75,color=c,lw=0))
        a.text(.8,y+.56,t,color=INK,fontsize=14,weight='bold')
        a.text(.8,y+.22,b,color=MUTED,fontsize=10.5)
        arrow(a,(6.4,y+.37),(6.85,y+.37),c)
        a.text(7.1,y+.56,rt,color=c,fontsize=13,weight='bold')
        a.text(7.1,y+.22,rb,color=MUTED,fontsize=10.5)
    footer(a,'Design: HadAgent arXiv:2604.18614v1, §§III-A–G. Implementation: the locally supplied podl_chain snapshot; exact upstream revision unverified.\nContribution: a bounded verifier audit and reproducible local evidence. No claim of breaking the complete consensus protocol.')
    save(f,'framework-scope')

def next_study():
    f,a=canvas('Compare score-only verification with a verifier-controlled reference',
        'Proposed next study · paired decisions on sealed held-out prompts · protocol only; no experiment has been run.',
        'Next study / proposed and unrun')

    stages=[
        (.6,4.25,'01  Calibrate, then freeze',
         'Find an eligible honest target. Fix the\nagreement rule, threshold, and stop rules.',BLUE),
        (5.8,4.25,'02  Commit the contract',
         'Artifact, task, decode, runtime, endpoint,\nand context hashes enter the signed ledger.',TEAL),
        (11.0,4.4,'03  Reveal held-out prompts',
         'Keep final challenges sealed until the\nendpoint, candidates, and thresholds are fixed.',BLUE),
    ]
    for x,w,title,body,color in stages:
        box(a,x,5.25,w,1.3,title,body,color,headsize=14,bodysize=10.5)
    arrow(a,(4.88,5.9),(5.72,5.9),BLUE)
    arrow(a,(10.08,5.9),(10.92,5.9),BLUE)

    box(a,.6,3.25,7.2,1.45,'Copied baseline · candidate endpoint',
        'The verifier queries the endpoint named in the PROOF,\nrecomputes task score, then applies  B = score ≥ threshold.',AMBER,
        headsize=15,bodysize=11)
    box(a,8.2,3.25,7.2,1.45,'Proposed audit · verifier-controlled target',
        'Send the same challenge to candidate and committed reference;\napply  R = B  AND  output agreement ≥ frozen threshold.',TEAL,
        headsize=15,bodysize=11)
    arrow(a,(13.2,5.2),(13.2,4.75),BLUE)
    arrow(a,(13.2,4.75),(4.2,4.75),AMBER,style='--',rad=.08)
    arrow(a,(13.2,4.75),(11.8,4.75),TEAL,style='--',rad=-.08)

    controls=[
        (.6,'Eligible honest target','Exact committed artifact;\nmust qualify and stay accepted.',TEAL),
        (4.4,'Alternate model','Preselected on calibration; useful\nonly if it passes the score gate.',BLUE),
        (8.2,'Cache / lookup','Calibration examples only; final\nchallenges remain sealed.',AMBER),
        (12.0,'Target proxy','Expected to pass; exposes the\nfresh-work limitation.',AMBER),
    ]
    a.text(.6,2.88,'PAIRED CANDIDATE ARMS AND CONTROLS',fontsize=11,color=MUTED,weight='bold')
    for x,title,body,color in controls:
        box(a,x,1.35,3.4,1.25,title,body,color,headsize=13,bodysize=9.8)

    footer(a,'Commitments make the declared contract tamper-evident; they do not prove that the candidate ran it. A passing proxy shows output consistency, not fresh prover work.\nPROPOSED / UNRUN: no model, paid compute, consensus network, or deployed system tested; not reviewed or approved by Dr. Boyang Li.')
    save(f,'next-study-protocol')

if __name__=='__main__':
    boundary();score_repair();baseline();framework();next_study()
    print('Created four evidence figures and one proposed-study diagram, each as editable SVG and PNG.')

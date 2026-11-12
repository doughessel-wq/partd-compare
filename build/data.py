import csv,json,pickle,collections,base64,statistics,re,os
C='ca2027/'
rxn={c['rxcui']:c['name'] for c in json.load(open('src/rxn.json'))['minConceptGroup']['minConcept']}
med,ndc2rx26,_=pickle.load(open('dl/price.pkl','rb'))
net,pref,pzip=pickle.load(open('dl/net.pkl','rb'))
npi=json.load(open('src/npi.json')) if os.path.exists('src/npi.json') else {}
# formularies
F=collections.defaultdict(dict); rxndc={}
for r in csv.DictReader(open(C+'basic_drugs_formulary_CA.txt'),delimiter='|'):
    fl=(r['QUANTITY_LIMIT_YN']=='Y')|((r['PRIOR_AUTHORIZATION_YN']=='Y')<<1)|((r['STEP_THERAPY_YN']=='Y')<<2)
    F[r['FORMULARY_ID']][r['RXCUI']]=int(r['TIER_LEVEL_VALUE'])*8+fl; rxndc.setdefault(r['RXCUI'],set()).add(r['NDC'])
rx26=collections.defaultdict(list)
for n,rc in ndc2rx26.items():
    if n in med: rx26[rc].append(med[n])
def price(rc):
    v=[med[n] for n in rxndc[rc] if n in med] or rx26.get(rc)
    return round(statistics.median(v),4) if v else None
drugs=sorted(([rc,rxn[rc],price(rc),1 if 'insulin' in rxn[rc].lower() else 0] for rc in rxndc),key=lambda d:d[1].lower())
print('drugs',len(drugs),'no price',sum(d[2] is None for d in drugs),'insulin',sum(d[3] for d in drugs))
fids=sorted(F); fidx={f:i for i,f in enumerate(fids)}
# stars
rows=list(csv.reader(open('src/stars/2027 Star Ratings Data Table - Summary Ratings (Oct 8 2026).csv',encoding='latin-1')))
ST={r[0].strip():[x.strip() for x in r] for r in rows[2:] if r and r[0].strip()}
def num(s):
    try: return float(s)
    except: return None
# costs
cost=collections.defaultdict(dict)
for r in csv.DictReader(open(C+'beneficiary_cost_CA.txt'),delimiter='|'):
    if r['DAYS_SUPPLY']=='1' and r['COVERAGE_LEVEL']=='1':
        cost[(r['CONTRACT_ID'],r['PLAN_ID'],r['SEGMENT_ID'])][r['TIER']]=[int(r['COST_TYPE_PREF']),float(r['COST_AMT_PREF']),int(r['COST_TYPE_NONPREF']),float(r['COST_AMT_NONPREF']),1 if r['DED_APPLIES_YN']=='Y' else 0]
ins=collections.defaultdict(dict)
def lo(*v):
    v=[float(x) for x in v if x.strip()]; return min(v) if v else None
for r in csv.DictReader(open(C+'insulin_beneficiary_cost_CA.txt'),delimiter='|'):
    if r['DAYS_SUPPLY']=='1':
        ins[(r['CONTRACT_ID'],r['PLAN_ID'],r['SEGMENT_ID'])][r['TIER']]=[lo(r['copay_amt_pref_insln']),lo(r['copay_amt_nonpref_insln'])]
# pharmacies
KEEP={'CVS','LLC','INC','RX','USA','UCSF','UCLA','VA','II','III','LP','MD','HMO','UC','USC','AHF','CA','DBA'}
def tc(s):
    return ' '.join(w if (w in KEEP or any(ch.isdigit() for ch in w)) else w.capitalize() for w in re.sub(r'\s+',' ',s or '').strip().upper().split(' '))
ph=[]
for p,z in pzip.items():
    r=npi.get(p[2:])
    if r: ph.append((p,[tc(r['dba'] or r['name']),tc(r['addr']),tc(r['city']),r['zip'] or z]))
    else: ph.append((p,['Pharmacy, NPI '+p[2:],'Address not on file','',z]))
ph.sort(key=lambda x:(x[1][3],x[1][0]))
pidx={p:i for i,(p,_) in enumerate(ph)}
print('pharmacies',len(ph),'named',sum(1 for p,_ in ph if p[2:] in npi))
def bits(s):
    b=bytearray((len(ph)+7)//8)
    for p in s: i=pidx[p]; b[i>>3]|=1<<(i&7)
    return base64.b64encode(bytes(b)).decode()
nets=[]; nkey={}
# plans
P=list(csv.DictReader(open(C+'plan_information_CA.txt',encoding='latin-1'),delimiter='|'))
grp=collections.OrderedDict()
for r in P: grp.setdefault((r['CONTRACT_ID'],r['PLAN_ID'],r['SEGMENT_ID']),[]).append(r)
plans=[]
for k,rs in grp.items():
    r=rs[0]; pdp=r['CONTRACT_ID'][0]=='S'
    s=ST.get(r['CONTRACT_ID'])
    star=None; kind=''; note='Not rated'
    if s:
        if pdp: star=num(s[9]); kind='Part D rating'; note=s[9]
        else:
            star=num(s[10]); kind='Overall rating'; note=s[10]
            if star is None and num(s[9]) is not None: star=num(s[9]); kind='Part D rating'
    nk=(frozenset(net.get(k,())),frozenset(pref.get(k,())))
    if nk not in nkey: nkey[nk]=len(nets); nets.append([bits(nk[0]),bits(nk[1])])
    plans.append(dict(id='-'.join(k),name=r['PLAN_NAME'].strip(),org=(s[3] if s else r['CONTRACT_NAME']).strip(),type='PDP' if pdp else 'MA',snp=int(r['SNP'] or 0),f=fidx[r['FORMULARY_ID']],prem=float(r['PREMIUM']),ded=float(r['DEDUCTIBLE']),cty=None if pdp else sorted({x['COUNTY_CODE'] for x in rs}),star=star,starKind=kind,starNote=note,net=nkey[nk],cost=cost[k],ins=ins.get(k,{})))
print('plans',len(plans),'nets',len(nets),'unrated',sum(p['star'] is None for p in plans))
# geography
geo=collections.defaultdict(list)
for r in csv.DictReader(open(C+'geographic_locator_CA.txt'),delimiter='|'):
    if '(Partial)' not in r['COUNTY']: geo[r['COUNTY'].strip()].append(r['COUNTY_CODE'])
z=collections.defaultdict(list)
for r in csv.DictReader(open('src/zcta.txt',encoding='utf-8-sig'),delimiter='|'):
    if r['GEOID_COUNTY_20'].startswith('06') and r['GEOID_ZCTA5_20']:
        z[r['GEOID_ZCTA5_20']].append((-int(r['AREALAND_PART']),r['NAMELSAD_COUNTY_20'].replace(' County','')))
zips={k:[n for _,n in sorted(v)] for k,v in z.items()}
di={d[0]:i for i,d in enumerate(drugs)}
ex95003=[i for i,(p,v) in enumerate(ph) if v[3]=='95003' and not v[0].startswith('Pharmacy, NPI')]
best=max(ex95003,key=lambda i:sum(1 for k in net if ph[i][0] in pref.get(k,())),default=None)
print('example pharmacy',ph[best][1] if best is not None else None)
D=dict(meta=dict(v='2027-1',cap=2400,planFile='release of 8 October 2026',priceFile='2026 third-quarter CMS pricing',example=dict(zip='95003',county='Santa Cruz',ph=best,rx=[dict(i=di['617310'],q=30),dict(i=di['314076'],q=30),dict(i=di['861007'],q=60),dict(i=di['1364447'],q=60),dict(i=di['1545664'],q=30)])),
  zips=zips,counties=dict(geo),plans=plans,forms=[F[f] for f in fids],drugs=drugs,pharm=[v for _,v in ph],nets=nets)
js=json.dumps(D,separators=(',',':')).replace('</','<\\/')
html=open('pd/app.html',encoding='utf-8').read().replace('/*DATA*/null',js)
os.makedirs('/home/user/partd-compare',exist_ok=True)
open('/home/user/partd-compare/index.html','w',encoding='utf-8').write('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>\n'+html+'\n</body></html>')
os.makedirs('pd/artifact',exist_ok=True)
open('pd/artifact/california-part-d-compare.html','w',encoding='utf-8').write(html)
print('bytes',len(html))

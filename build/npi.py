import pickle,json,urllib.request,urllib.parse,concurrent.futures as cf,time,collections
net,pref,zips=pickle.load(open('dl/net.pkl','rb'))
want={p[2:]:p for p in zips}
out={}
def get(params):
    u='https://npiregistry.cms.hhs.gov/api/?version=2.1&'+urllib.parse.urlencode(params)
    for a in range(4):
        try: return json.load(urllib.request.urlopen(u,timeout=60)).get('results',[]) or []
        except Exception as e: time.sleep(2*(a+1))
    return []
def rec(r):
    b=r.get('basic',{}); loc=[a for a in r.get('addresses',[]) if a.get('address_purpose')=='LOCATION'] or r.get('addresses',[{}])
    a=loc[0]
    dba=[o.get('organization_name') for o in r.get('other_names',[]) if o.get('type','').lower().startswith('doing') and o.get('organization_name')]
    return dict(name=b.get('organization_name') or ' '.join(filter(None,[b.get('first_name'),b.get('last_name')])),dba=dba[0] if dba else None,addr=' '.join(filter(None,[a.get('address_1'),a.get('address_2')])),city=a.get('city'),zip=(a.get('postal_code') or '')[:5])
def byzip(z):
    res=[]
    for skip in (0,200,400):
        r=get(dict(enumeration_type='NPI-2',taxonomy_description='pharmacy',state='CA',postal_code=z,limit=200,skip=skip))
        res+=r
        if len(r)<200: break
    return res
zs=sorted(set(zips.values()))
with cf.ThreadPoolExecutor(6) as ex:
    for res in ex.map(byzip,zs):
        for r in res:
            if str(r['number']) in want: out[str(r['number'])]=rec(r)
print('after zip pass',len(out),'of',len(want),flush=True)
miss=[n for n in want if n not in out]
def one(n):
    r=get(dict(number=n)); return n,(rec(r[0]) if r else None)
with cf.ThreadPoolExecutor(6) as ex:
    for n,r in ex.map(one,miss):
        if r: out[n]=r
print('final',len(out),'of',len(want))
json.dump(out,open('src/npi.json','w'))

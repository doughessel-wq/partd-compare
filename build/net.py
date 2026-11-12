import zipfile,sys,pickle,csv,collections,os
part=sys.argv[1]
plans={(r['CONTRACT_ID'],r['PLAN_ID'],r['SEGMENT_ID']) for r in csv.DictReader(open('ca2027/plan_information_CA.txt',encoding='latin-1'),delimiter='|')}
contracts={p[0].encode() for p in plans}
z=zipfile.ZipFile('dl/m2027.zip')
name=[n for n in z.namelist() if f'part {part}' in n][0]
tmp=f'dl/part{part}.zip'
with z.open(name) as s, open(tmp,'wb') as o:
    while True:
        b=s.read(1<<24)
        if not b: break
        o.write(b)
inner=zipfile.ZipFile(tmp)
net=collections.defaultdict(set); pref=collections.defaultdict(set); zips={}
n=0
with inner.open(inner.namelist()[0]) as f:
    for line in f:
        if line[:5] not in contracts: continue
        x=line.split(b'|')
        if x[7]!=b'Y': continue
        zc=x[4]
        if not (b'90000'<=zc[:5]<=b'96199'): continue
        k=(x[0].decode(),x[1].decode(),x[2].decode())
        if k not in plans: continue
        ph=x[3].decode()
        net[k].add(ph); zips[ph]=zc[:5].decode()
        if x[5]==b'Y': pref[k].add(ph)
        n+=1
pickle.dump((dict(net),dict(pref),zips),open(f'dl/net{part}.pkl','wb'))
os.remove(tmp)
print(part,n,len(net),len(zips))

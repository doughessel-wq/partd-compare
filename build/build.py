#!/usr/bin/env python3
"""Rebuild index.html from CMS public data.

    python3 build/build.py

Downloads what it needs into .cache/ (about 5 GB, reused on later runs), keeps
California only, and writes index.html. Settings live in config.json.
Standard library only; needs Python 3.9+ and network access to data.cms.gov,
www.cms.gov, rxnav.nlm.nih.gov, www2.census.gov and npiregistry.cms.hhs.gov.
"""
import argparse, base64, collections, concurrent.futures as cf, csv, io, json, os, re
import shutil, statistics, sys, time, urllib.parse, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, '.cache')
UA = {'User-Agent': 'Mozilla/5.0 (partd-compare build)'}
CATALOG = 'https://data.cms.gov/data.json'
STARS_PAGE = 'https://www.cms.gov/medicare/health-drug-plans/part-c-d-performance-data'
LANDSCAPE_PAGE = 'https://www.cms.gov/medicare/coverage/prescription-drug-coverage'
RXNORM = 'https://rxnav.nlm.nih.gov/REST/allconcepts.json?tty=SCD+SBD+GPCK+BPCK'
ZCTA = 'https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt'
GAZETTEER = 'https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_zcta_national.zip'
NPI_API = 'https://npiregistry.cms.hhs.gov/api/?version=2.1&'
PDP_REGION_CA, CA_FIPS = '32', '06'


def log(*a):
    print(*a, flush=True)


def fetch(url, name=None, refresh=False):
    """Download url into the cache (once) and return the local path."""
    path = os.path.join(CACHE, name or os.path.basename(urllib.parse.urlparse(url).path))
    if os.path.exists(path) and not refresh:
        return path
    log('  downloading', url)
    tmp = path + '.part'
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(tmp, 'wb') as o:
                shutil.copyfileobj(r, o, 1 << 22)
            os.replace(tmp, path)
            return path
        except Exception as e:
            if attempt == 3:
                raise SystemExit(f'Could not download {url}: {e}')
            time.sleep(5 * (attempt + 1))


def zip_centres(year, refresh):
    """Latitude and longitude of each ZIP Code Tabulation Area, from the newest Census gazetteer."""
    path = None
    for y in range(year, 2019, -1):
        name = f'{y}_Gaz_zcta_national.zip'
        if os.path.exists(os.path.join(CACHE, name)) and not refresh:
            path = os.path.join(CACHE, name); break
        try:
            req = urllib.request.Request(GAZETTEER.format(y=y), headers=UA, method='HEAD')
            if urllib.request.urlopen(req, timeout=60).status == 200:
                path = fetch(GAZETTEER.format(y=y), name, refresh); break
        except Exception:
            continue
    if not path:
        raise SystemExit('No Census ZIP gazetteer file found.')
    z = zipfile.ZipFile(path)
    t = io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig')
    first = t.readline(); sep = '|' if '|' in first else '\t'
    h = [c.strip() for c in first.split(sep)]
    i_lat, i_lon = h.index('INTPTLAT'), h.index('INTPTLONG')
    out = {}
    for line in t:
        r = [c.strip() for c in line.split(sep)]
        if len(r) > i_lon:
            out[r[0]] = [round(float(r[i_lat]), 3), round(float(r[i_lon]), 3)]
    return out


def star_detail(zip_path, contracts):
    """Everything CMS publishes behind a contract's star rating: summary, domain and measure stars, measure results."""
    z = zipfile.ZipFile(zip_path)

    def rows(key):
        name = [n for n in z.namelist() if key in n and n.lower().endswith('.csv')]
        if not name:
            raise SystemExit(f'No "{key}" table in the star ratings zip.')
        rr = list(csv.reader(io.TextIOWrapper(z.open(name[0]), encoding='cp1252')))
        hi = next(i for i, r in enumerate(rr) if r and r[0].strip().upper().replace('_', ' ') in ('CONTRACT NUMBER', 'CONTRACT ID'))
        return rr, hi

    def val(s):
        s = s.strip()
        try:
            f = float(s)
            return int(f) if f == int(f) else f
        except ValueError:
            return s

    clean = lambda s: re.sub(r'\s+', ' ', s.replace('\x96', '-').replace('–', '-').replace('’', "'")).strip()
    sr, shi = rows('Summary Ratings'); sh = [c.strip() for c in sr[shi]]
    s_cols = [next(i for i, c in enumerate(sh) if c.endswith(k)) for k in ('Part C Summary', 'Part D Summary', 'Overall')]
    dr, dhi = rows('Domain Stars'); dh = [c.strip() for c in dr[dhi]]
    d_cols = [i for i, c in enumerate(dh) if re.match(r'[HD]D\d+:', c)]
    domains = [[dh[i].split(':')[0], clean(dh[i].split(':', 1)[1])] for i in d_cols]
    mr, mhi = rows('Measure Stars')
    groups, names, dates = mr[mhi], mr[mhi + 1], mr[mhi + 2]
    m_cols = [i for i, c in enumerate(names) if re.match(r'[CD]\d+:', c.strip())]
    dom_at = {}
    cur = None
    for i, c in enumerate(groups):
        if re.match(r'[HD]D\d+:', c.strip()):
            cur = [d[0] for d in domains].index(c.strip().split(':')[0])
        dom_at[i] = cur
    measures = [[names[i].strip().split(':')[0], clean(names[i].split(':', 1)[1]), dom_at.get(i), clean(dates[i])] for i in m_cols]
    vr, vhi = rows('Measure Data')
    if any(i >= len(vr[vhi + 1]) or vr[vhi + 1][i].strip() != names[i].strip() for i in m_cols):
        raise SystemExit('Star measure tables do not line up.')
    by = lambda rr, hi, skip: {r[0].strip(): r for r in rr[hi + skip:] if r and r[0].strip()}
    S, Dm, Ms, Mv = by(sr, shi, 1), by(dr, dhi, 1), by(mr, mhi, 3), by(vr, vhi, 3)
    hp, lp = {}, {}
    hr, hhi = rows('High Performing'); hh = [c.strip() for c in hr[hhi]]
    for c, r in by(hr, hhi, 1).items():
        hp[c] = clean(r[hh.index('Highest Rating')]) if 'Highest Rating' in hh else 'Yes'
    lr, lhi = rows('Low Performing'); lh = [c.strip() for c in lr[lhi]]
    for c, r in by(lr, lhi, 1).items():
        lp[c] = clean(r[lh.index('Reason for LPI')]) if 'Reason for LPI' in lh else 'Yes'
    out = {}
    for c in contracts:
        if c not in S:
            continue
        out[c] = dict(s=[val(S[c][i]) for i in s_cols], d=[val(Dm[c][i]) for i in d_cols] if c in Dm else None,
                      m=[val(Ms[c][i]) for i in m_cols] if c in Ms else None, v=[val(Mv[c][i]) for i in m_cols] if c in Mv else None,
                      hp=hp.get(c), lp=lp.get(c))
    return dict(domains=domains, measures=measures, c=out)


def inner(outer_path, key, tag):
    """Open the text file inside the nested zip whose name contains key."""
    z = zipfile.ZipFile(outer_path)
    names = [n for n in z.namelist() if key in n.lower() and 'sample' not in n.lower()]
    if not names:
        raise SystemExit(f'No "{key}" file inside {os.path.basename(outer_path)}')
    names.sort(key=lambda n: not n.lower().startswith(key))
    tmp = os.path.join(CACHE, f'tmp_{tag}.zip')
    with z.open(names[0]) as s, open(tmp, 'wb') as o:
        shutil.copyfileobj(s, o, 1 << 24)
    iz = zipfile.ZipFile(tmp)
    return iz.open(iz.namelist()[0]), tmp


def table(outer_path, key):
    f, tmp = inner(outer_path, key, re.sub(r'\W', '', key))
    rows = list(csv.DictReader(io.TextIOWrapper(f, encoding='latin-1'), delimiter='|'))
    f.close(); os.remove(tmp)
    return rows


def is_ca(r):
    return r['STATE'].strip() == 'CA' or r['PDP_REGION_CODE'].strip() == PDP_REGION_CA


def plan_key(r):
    return (r['CONTRACT_ID'], r['PLAN_ID'], r['SEGMENT_ID'])


# ---------- finding the source files ----------
def discover(cfg, refresh):
    year, ov = cfg['plan_year'], cfg.get('url_overrides', {})
    monthly, quarterly, mdate = ov.get('monthly_zip'), ov.get('quarterly_zip'), ''
    if not (monthly and quarterly):
        cat = json.load(open(fetch(CATALOG, 'catalog.json', refresh=True), encoding='utf-8'))
        m, q = [], []
        for ds in cat['dataset']:
            t = ds['title']
            for d in ds.get('distribution', []):
                u = d.get('downloadURL')
                if not u:
                    continue
                date = t.split(' : ')[-1]
                if t.startswith('Monthly Prescription Drug Plan Formulary') and os.path.basename(u).startswith(f'{year}_'):
                    m.append((date, u))
                if t.startswith('Quarterly Prescription Drug Plan Formulary'):
                    q.append((date, u))
        if not monthly:
            if not m:
                raise SystemExit(f'CMS has no monthly formulary file for plan year {year} yet.')
            mdate, monthly = max(m)
        if not quarterly:
            quarterly = max(q)[1]
    stars = ov.get('star_ratings_zip')
    if not stars:
        html = open(fetch(STARS_PAGE, 'stars_page.html', refresh=True), encoding='utf-8', errors='replace').read()
        links = re.findall(rf'href="(/files/zip/{year}-star-ratings-data-tables[^"]*\.zip)"', html)
        if not links:
            raise SystemExit(f'No {year} star ratings data tables on the CMS page.')
        stars = 'https://www.cms.gov' + links[0]
    land = ov.get('landscape_zip')
    if not land:
        html = open(fetch(LANDSCAPE_PAGE, 'landscape_page.html', refresh=True), encoding='utf-8', errors='replace').read()
        links = sorted(set(re.findall(rf'href="(/files/zip/cy{year}-landscape-[^"]*\.zip)"', html)))
        if not links:
            raise SystemExit(f'No CY{year} landscape file on the CMS page.')
        land = 'https://www.cms.gov' + links[-1]
    return monthly, quarterly, stars, land, mdate


def money(s):
    """'$1,234.50 ' -> 1234.5, '($14.20)' -> -14.2, anything else -> None."""
    t = s.strip().replace('$', '').replace(',', '')
    neg = t.startswith('(') and t.endswith(')')
    try:
        return -float(t[1:-1]) if neg else float(t)
    except ValueError:
        return None


def landscape(path):
    """Premiums per California plan from the CMS landscape file."""
    z = zipfile.ZipFile(path)
    name = [n for n in z.namelist() if n.lower().endswith('.csv')]
    if not name:
        raise SystemExit('No CSV inside the landscape zip.')
    out = {}
    for r in csv.DictReader(io.TextIOWrapper(z.open(name[0]), encoding='utf-8-sig', errors='replace')):
        if r['State Territory Abbreviation'] != 'CA':
            continue
        k = (r['Contract ID'], r['Plan ID'].zfill(3), r['Segment ID'].zfill(3))
        out[k] = dict(d=money(r['Part D Total Premium']), lis=money(r['Part D Low Income Beneficiary Premium Amount']),
                      c=money(r['Part C Premium']), both=money(r['Monthly Consolidated Premium (Part C + D)']))
    return out


# ---------- pharmacy networks ----------
def network_part(args):
    outer, name, plans, part = args
    contracts = {p[0].encode() for p in plans}
    tmp = os.path.join(CACHE, f'tmp_net{part}.zip')
    with zipfile.ZipFile(outer).open(name) as s, open(tmp, 'wb') as o:
        shutil.copyfileobj(s, o, 1 << 24)
    iz = zipfile.ZipFile(tmp)
    net, pref, zips = collections.defaultdict(set), collections.defaultdict(set), {}
    with iz.open(iz.namelist()[0]) as f:
        h = f.readline().decode().strip().split('|')
        i_ph, i_zip, i_pref, i_retail = (h.index(c) for c in ('PHARMACY_NUMBER', 'PHARMACY_ZIPCODE', 'PREFERRED_STATUS_RETAIL', 'PHARMACY_RETAIL'))
        for line in f:
            if line[:5] not in contracts:
                continue
            x = line.split(b'|')
            if x[i_retail] != b'Y' or not (b'90000' <= x[i_zip][:5] <= b'96199'):
                continue
            k = (x[0].decode(), x[1].decode(), x[2].decode())
            if k not in plans:
                continue
            ph = x[i_ph].decode()
            net[k].add(ph); zips[ph] = x[i_zip][:5].decode()
            if x[i_pref] == b'Y':
                pref[k].add(ph)
    os.remove(tmp)
    return dict(net), dict(pref), zips


def networks(outer, plans):
    names = sorted(n for n in zipfile.ZipFile(outer).namelist() if 'pharmacy networks' in n.lower() and 'sample' not in n.lower())
    net, pref, zips = collections.defaultdict(set), collections.defaultdict(set), {}
    with cf.ProcessPoolExecutor(min(len(names), os.cpu_count() or 2)) as ex:
        for a, b, c in ex.map(network_part, [(outer, n, plans, i) for i, n in enumerate(names)]):
            for k, v in a.items(): net[k] |= v
            for k, v in b.items(): pref[k] |= v
            zips.update(c)
    return net, pref, zips


# ---------- pharmacy names ----------
def npi_get(params):
    u = NPI_API + urllib.parse.urlencode(params)
    for a in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60)).get('results') or []
        except Exception:
            time.sleep(2 * (a + 1))
    return []


def npi_record(r):
    b = r.get('basic', {})
    a = ([x for x in r.get('addresses', []) if x.get('address_purpose') == 'LOCATION'] or r.get('addresses') or [{}])[0]
    dba = [o.get('organization_name') for o in r.get('other_names', []) if o.get('type', '').lower().startswith('doing') and o.get('organization_name')]
    return dict(name=b.get('organization_name') or ' '.join(filter(None, [b.get('first_name'), b.get('last_name')])),
                dba=dba[0] if dba else None, addr=' '.join(filter(None, [a.get('address_1'), a.get('address_2')])),
                city=a.get('city'), zip=(a.get('postal_code') or '')[:5])


def npi_zip(z):
    out = []
    for skip in (0, 200, 400):
        r = npi_get(dict(enumeration_type='NPI-2', taxonomy_description='pharmacy', state='CA', postal_code=z, limit=200, skip=skip))
        out += r
        if len(r) < 200:
            break
    return out


def pharmacy_names(pzip):
    path = os.path.join(CACHE, 'npi.json')
    known = json.load(open(path)) if os.path.exists(path) else {}
    want = {p[2:] for p in pzip}
    missing = want - set(known)
    if missing:
        log(f'  looking up {len(missing):,} pharmacy names')
        zs = sorted({pzip['10' + n] for n in missing if '10' + n in pzip}) if len(missing) > 300 else []
        with cf.ThreadPoolExecutor(6) as ex:
            for res in ex.map(npi_zip, zs):
                for r in res:
                    if str(r['number']) in want:
                        known[str(r['number'])] = npi_record(r)
            for n, r in ex.map(lambda n: (n, npi_get(dict(number=n))), sorted(want - set(known))):
                if r:
                    known[n] = npi_record(r[0])
        json.dump(known, open(path, 'w'))
    return known


KEEP_UPPER = {'CVS', 'LLC', 'INC', 'RX', 'USA', 'UCSF', 'UCLA', 'VA', 'II', 'III', 'LP', 'MD', 'HMO', 'UC', 'USC', 'AHF', 'CA', 'DBA'}


def title(s):
    words = re.sub(r'\s+', ' ', s or '').strip().upper().split(' ')
    return ' '.join(w if (w in KEEP_UPPER or any(c.isdigit() for c in w)) else w.capitalize() for w in words)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--refresh', action='store_true', help='download reference files again (drug names, ZIP table)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'index.html'))
    args = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    year = cfg['plan_year']
    os.makedirs(CACHE, exist_ok=True)

    log('1/7 Finding the latest CMS files')
    m_url, q_url, s_url, l_url, m_date = discover(cfg, args.refresh)
    monthly, quarterly, stars_zip, land_zip = fetch(m_url), fetch(q_url), fetch(s_url), fetch(l_url)
    log('   plans:  ', os.path.basename(monthly)); log('   prices: ', os.path.basename(quarterly)); log('   stars:  ', os.path.basename(stars_zip)); log('   premiums:', os.path.basename(land_zip))

    log('2/7 Plans, drug lists and cost sharing')
    plan_rows = [r for r in table(monthly, 'plan information') if is_ca(r)]
    if not plan_rows:
        raise SystemExit('No California plans found in the monthly file.')
    groups = collections.OrderedDict()
    for r in plan_rows:
        groups.setdefault(plan_key(r), []).append(r)
    plans_set = set(groups)
    fids_used = {r['FORMULARY_ID'] for r in plan_rows}
    forms, rx_ndc, years = collections.defaultdict(dict), {}, set()
    for r in table(monthly, 'basic drugs formulary'):
        if r['FORMULARY_ID'] not in fids_used:
            continue
        years.add(r['CONTRACT_YEAR'])
        flags = (r['QUANTITY_LIMIT_YN'] == 'Y') | ((r['PRIOR_AUTHORIZATION_YN'] == 'Y') << 1) | ((r['STEP_THERAPY_YN'] == 'Y') << 2)
        code = int(r['TIER_LEVEL_VALUE']) * 8 + flags
        # a quantity limit is "amount per days", e.g. 30 per 30 days; keep it where CMS gives both numbers
        try:
            amt, days = float(r['QUANTITY_LIMIT_AMOUNT']), int(float(r['QUANTITY_LIMIT_DAYS']))
            limit = [int(amt) if amt == int(amt) else amt, days] if (flags & 1 and amt > 0 and days > 0) else None
        except ValueError:
            limit = None
        forms[r['FORMULARY_ID']][r['RXCUI']] = [code] + limit if limit else code
        rx_ndc.setdefault(r['RXCUI'], set()).add(r['NDC'])
    if years != {str(year)}:
        raise SystemExit(f'Monthly file is for contract year {sorted(years)}, but config.json says {year}.')
    # DAYS_SUPPLY: 1 = 30 days, 2 = 90 days (CMS record layout). COVERAGE_LEVEL 1 = initial coverage.
    cost, cost90 = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in table(monthly, 'beneficiary cost file'):
        if plan_key(r) not in plans_set or r['COVERAGE_LEVEL'] != '1':
            continue
        ded = 1 if r['DED_APPLIES_YN'] == 'Y' else 0
        if r['DAYS_SUPPLY'] == '1':
            cost[plan_key(r)][r['TIER']] = [int(r['COST_TYPE_PREF']), float(r['COST_AMT_PREF']), int(r['COST_TYPE_NONPREF']),
                                             float(r['COST_AMT_NONPREF']), ded]
        elif r['DAYS_SUPPLY'] == '2':
            # retail preferred, retail standard, mail preferred, mail standard (type, amount each), deductible flag
            cost90[plan_key(r)][r['TIER']] = [int(r['COST_TYPE_PREF']), float(r['COST_AMT_PREF']), int(r['COST_TYPE_NONPREF']), float(r['COST_AMT_NONPREF']),
                                               int(r['COST_TYPE_MAIL_PREF']), float(r['COST_AMT_MAIL_PREF']), int(r['COST_TYPE_MAIL_NONPREF']),
                                               float(r['COST_AMT_MAIL_NONPREF']), ded]
    low = lambda *v: min([float(x) for x in v if x.strip()], default=None)
    insulin, insulin90 = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in table(monthly, 'insulin beneficiary cost'):
        if plan_key(r) not in plans_set:
            continue
        if r['DAYS_SUPPLY'] == '1':
            insulin[plan_key(r)][r['TIER']] = [low(r['copay_amt_pref_insln']), low(r['copay_amt_nonpref_insln'])]
        elif r['DAYS_SUPPLY'] == '2':
            insulin90[plan_key(r)][r['TIER']] = [low(r['copay_amt_pref_insln']), low(r['copay_amt_nonpref_insln']),
                                                 low(r['copay_amt_mail_pref_insln']), low(r['copay_amt_mail_nonpref_insln'])]
    geo = collections.defaultdict(list)
    for r in table(monthly, 'geographic locator'):
        if r['STATENAME'].strip() == 'California' and '(Partial)' not in r['COUNTY']:
            geo[r['COUNTY'].strip()].append(r['COUNTY_CODE'])
    land = landscape(land_zip)
    no_land = [k for k in groups if k not in land]
    differ = [k for k, rs in groups.items() if k in land and land[k]['d'] is not None and abs(land[k]['d'] - float(rs[0]['PREMIUM'])) > 0.005]
    log(f'   {len(groups)} plans, {len(forms)} drug lists; {len(no_land)} plans missing from the landscape file, '
        f'{len(differ)} with a different drug premium there')

    log('3/7 Pharmacy networks (the slow step)')
    net, pref, pzip = networks(monthly, plans_set)
    log(f'   {len(pzip):,} California pharmacies')

    log('4/7 Drug prices')
    q_plans = {plan_key(r) for r in table(quarterly, 'plan information') if is_ca(r)}
    q_form = table(quarterly, 'basic drugs formulary')
    price_year = int(q_form[0]['CONTRACT_YEAR'])
    ndc_rx = {r['NDC']: r['RXCUI'] for r in q_form}
    del q_form
    f, tmp = inner(quarterly, 'pricing file', 'pricing')
    h = f.readline().decode().strip().split('|')
    i_ndc, i_days, i_cost = h.index('NDC'), h.index('DAYS_SUPPLY'), h.index('UNIT_COST')
    q_contracts = {p[0].encode() for p in q_plans}
    by_ndc = collections.defaultdict(list)
    for line in f:
        if line[:5] not in q_contracts:
            continue
        x = line.rstrip().split(b'|')
        if x[i_days] == b'30' and (x[0].decode(), x[1].decode(), x[2].decode()) in q_plans:
            by_ndc[x[i_ndc].decode()].append(float(x[i_cost]))
    f.close(); os.remove(tmp)
    med = {k: statistics.median(v) for k, v in by_ndc.items()}
    by_rx = collections.defaultdict(list)
    for n, rc in ndc_rx.items():
        if n in med:
            by_rx[rc].append(med[n])

    def price(rc):
        v = [med[n] for n in rx_ndc[rc] if n in med] or by_rx.get(rc)
        return round(statistics.median(v), 4) if v else None
    log(f'   {len(med):,} priced products from plan year {price_year}')

    log('5/7 Drug names, star ratings, ZIP codes')
    concepts = json.load(open(fetch(RXNORM, 'rxnorm.json', args.refresh)))['minConceptGroup']['minConcept']
    rxn = {c['rxcui']: c['name'] for c in concepts}
    generic = {c['rxcui'] for c in concepts if c['tty'] in ('SCD', 'GPCK')}
    drugs = sorted(([rc, rxn.get(rc, f'Unnamed drug (RxNorm {rc})'), price(rc), 1 if 'insulin' in rxn.get(rc, '').lower() else 0, 1 if rc in generic else 0] for rc in rx_ndc),
                   key=lambda d: d[1].lower())
    sz = zipfile.ZipFile(stars_zip)
    sname = [n for n in sz.namelist() if 'summary rating' in n.lower() and n.lower().endswith('.csv')]
    if not sname:
        raise SystemExit('No Summary Ratings table in the star ratings zip.')
    srows = list(csv.reader(io.TextIOWrapper(sz.open(sname[0]), encoding='latin-1')))
    hi = next(i for i, r in enumerate(srows) if r and r[0].strip() == 'Contract Number')
    hdr = [c.strip() for c in srows[hi]]
    c_name = hdr.index('Organization Marketing Name')
    c_d = next(i for i, c in enumerate(hdr) if c.endswith('Part D Summary'))
    c_o = next(i for i, c in enumerate(hdr) if c.endswith('Overall'))
    stars = {r[0].strip(): [x.strip() for x in r] for r in srows[hi + 1:] if r and r[0].strip()}
    star_more = star_detail(stars_zip, sorted({k[0] for k in groups}))
    log(f'   star detail for {len(star_more["c"])} contracts: {len(star_more["domains"])} domains, {len(star_more["measures"])} measures, '
        f'{sum(1 for v in star_more["c"].values() if v["lp"])} low-performing, {sum(1 for v in star_more["c"].values() if v["hp"])} high-performing')
    zc = collections.defaultdict(list)
    for r in csv.DictReader(open(fetch(ZCTA, 'zcta_county.txt', args.refresh), encoding='utf-8-sig'), delimiter='|'):
        if r['GEOID_COUNTY_20'].startswith(CA_FIPS) and r['GEOID_ZCTA5_20']:
            zc[r['GEOID_ZCTA5_20']].append((-int(r['AREALAND_PART']), r['NAMELSAD_COUNTY_20'].replace(' County', '')))
    zips = {k: [n for _, n in sorted(v)] for k, v in zc.items()}
    centres = zip_centres(year, args.refresh)

    log('6/7 Pharmacy names')
    npi = pharmacy_names(pzip)
    ph = []
    for p, z in pzip.items():
        r = npi.get(p[2:])
        ph.append((p, [title(r['dba'] or r['name']), title(r['addr']), title(r['city']), r['zip'] or z] if r
                   else ['Pharmacy, NPI ' + p[2:], 'Address not on file', '', z]))
    ph.sort(key=lambda x: (x[1][3], x[1][0], x[0]))
    pidx = {p: i for i, (p, _) in enumerate(ph)}

    def bits(s):
        b = bytearray((len(ph) + 7) // 8)
        for p in s:
            b[pidx[p] >> 3] |= 1 << (pidx[p] & 7)
        return base64.b64encode(bytes(b)).decode()

    log('7/7 Writing the app')
    def num(s):
        try: return float(s)
        except ValueError: return None
    fids = sorted(forms); fidx = {f: i for i, f in enumerate(fids)}
    nets, nkey, plans = [], {}, []
    for k, rs in groups.items():
        r = rs[0]; pdp = r['CONTRACT_ID'][0] == 'S'; s = stars.get(r['CONTRACT_ID'])
        star, kind, note = None, '', 'Not rated'
        if s:
            star, kind, note = (num(s[c_d]), 'Part D rating', s[c_d]) if pdp else (num(s[c_o]), 'Overall rating', s[c_o])
            if star is None and num(s[c_d]) is not None:
                star, kind = num(s[c_d]), 'Part D rating'
        nk = (frozenset(net.get(k, ())), frozenset(pref.get(k, ())))
        if nk not in nkey:
            nkey[nk] = len(nets); nets.append([bits(nk[0]), bits(nk[1])])
        prem, prem_lis, L = float(r['PREMIUM']), None, land.get(k)
        if L:
            part_c = 0.0 if pdp else (L['c'] or 0.0)
            if not pdp and L['both'] is not None:
                prem = L['both']
            if L['lis'] is not None:
                prem_lis = round(part_c + L['lis'], 2)
        plans.append(dict(id='-'.join(k), name=r['PLAN_NAME'].strip(), org=(s[c_name] if s else r['CONTRACT_NAME']).strip(),
                          type='PDP' if pdp else 'MA', snp=int(r['SNP'] or 0), f=fidx[r['FORMULARY_ID']], prem=prem, premLis=prem_lis,
                          ded=float(r['DEDUCTIBLE']), cty=None if pdp else sorted({x['COUNTY_CODE'] for x in rs}), star=star,
                          starKind=kind, starNote=note, net=nkey[nk], cost=cost[k], ins=insulin.get(k, {}), c90=cost90.get(k, {}), ins90=insulin90.get(k, {})))
    # ZIP centres for every ZIP a person can enter and every pharmacy ZIP; a pharmacy ZIP with no area of its own
    # (a PO box or single-building ZIP) borrows the centre of the closest-numbered ZIP that has one.
    have = sorted(z for z in centres if z[:1] == '9')
    zll, borrowed = {}, 0
    for z in set(zips) | {v[3] for _, v in ph}:
        if z in centres:
            zll[z] = centres[z]
        elif z.isdigit() and have:
            zll[z] = centres[min(have, key=lambda h: abs(int(h) - int(z)))]; borrowed += 1
    log(f'   {len(zll):,} ZIP centres for distances ({borrowed} borrowed from a neighbouring ZIP)')
    di = {d[0]: i for i, d in enumerate(drugs)}
    ex = cfg['example']
    local = [i for i, (p, v) in enumerate(ph) if v[3] == ex['zip'] and not v[0].startswith('Pharmacy, NPI')]
    ex_ph = max(local, key=lambda i: sum(1 for k in net if ph[i][0] in pref.get(k, ())), default=None)
    q_name = os.path.basename(quarterly)
    price_note = (f'Each drug uses the median price across California plans in the CMS {price_year} pricing file ({q_name}).' if price_year == year else
                  f'CMS has not yet published {year} plan prices, so each drug uses the median price across California plans in the {price_year} CMS pricing file ({q_name}).')
    eh = cfg['extra_help_copays']
    data = dict(meta=dict(v=f'{year}-{os.path.basename(monthly)}-eh', year=year, cap=cfg['out_of_pocket_cap'],
                          lis=dict(std=[eh['standard']['generic'], eh['standard']['brand']], low=[eh['lower']['generic'], eh['lower']['brand']]),
                          landscapeFile=os.path.basename(land_zip),
                          planFile=(f'release of {m_date}, ' if m_date else '') + os.path.basename(monthly), priceNote=price_note,
                          example=dict(zip=ex['zip'], county=ex['county'], ph=ex_ph,
                                       rx=[dict(i=di[x['rxcui']], q=x['quantity']) for x in ex['prescriptions'] if x['rxcui'] in di])),
                zips=zips, zll=zll, stars=star_more, counties=dict(geo), plans=plans, forms=[forms[f] for f in fids], drugs=drugs, pharm=[v for _, v in ph], nets=nets)
    page = open(os.path.join(ROOT, 'build', 'app.html'), encoding='utf-8').read().replace('{{YEAR}}', str(year))
    page = page.replace('/*DATA*/null', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))
    doc = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>\n'
           + page + '\n</body></html>')
    open(args.out, 'w', encoding='utf-8').write(doc)
    unrated = sum(p['star'] is None for p in plans)
    log(f'Done: {args.out} ({len(doc) / 1e6:.1f} MB)')
    log(f'   {len(plans)} plans ({unrated} unrated), {len(drugs):,} drugs ({sum(d[2] is None for d in drugs)} unpriced), '
        f'{len(ph):,} pharmacies ({sum(1 for p, _ in ph if p[2:] not in npi)} unnamed), {len(nets)} networks')


if __name__ == '__main__':
    main()

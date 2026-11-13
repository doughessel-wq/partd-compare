# California Part D Compare

A single-page tool that estimates Medicare Part D costs for California plans.
People answer five questions, add their prescriptions and pharmacy, and compare
estimated yearly costs and star ratings across plans.

**Live app: https://doughessel-wq.github.io/partd-compare/**

`index.html` is the finished app with all data embedded. GitHub Pages serves it
from the `main` branch, so every push to `main` updates the live app within a
minute or two. It can also be opened directly in a browser or uploaded to any
other static web host.

Estimates only. Not affiliated with Medicare.gov.

## Rebuilding the app

```bash
python3 build/build.py
```

That one command finds the newest CMS files for the plan year, downloads them,
keeps California only, and rewrites `index.html`. It prints a one-line summary
of plans, drugs and pharmacies when it finishes.

- **Needs:** Python 3.9 or later (no extra packages), about 6 GB of free disk,
  and network access to `data.cms.gov`, `www.cms.gov`, `rxnav.nlm.nih.gov`,
  `www2.census.gov` and `npiregistry.cms.hhs.gov`.
- **Time:** about 15 minutes the first time. Later runs reuse downloads kept in
  `.cache/` and only fetch files CMS has newly released.
- **Options:** `--refresh` downloads the drug-name and ZIP-code tables again;
  `--out FILE` writes somewhere other than `index.html`.

### When to run it

- **Monthly**, to pick up CMS updates to plans, drug lists and pharmacy networks.
- **When CMS publishes pricing for the plan year.** The build always uses the
  newest quarterly pricing file and words the in-app note to match the year the
  prices come from.
- **Each new plan year.** Edit `config.json` first (see below).

## Settings (`config.json`)

| Setting | What it is |
| --- | --- |
| `plan_year` | The plan year to build. The build stops if CMS has no file for it yet. |
| `out_of_pocket_cap` | The yearly cap on what a member pays for covered drugs. Set by CMS each year; check it when changing `plan_year`. |
| `example` | The sample ZIP code and prescriptions the app opens with. |
| `url_overrides` | Leave blank to use the newest files. Paste a direct zip link to pin a specific CMS release. |

## Files

- `build/build.py` — the build.
- `build/app.html` — the page: layout, questions and the cost calculation.
- `config.json` — settings.
- `.cache/` — downloads, not committed.

## Data sources

- CMS Monthly Prescription Drug Plan Formulary and Pharmacy Network Information (data.cms.gov)
- CMS Quarterly Prescription Drug Plan Formulary, Pharmacy Network, and Pricing Information (data.cms.gov)
- CMS Star Ratings data tables (cms.gov)
- NLM RxNorm for drug names, CMS NPI Registry for pharmacy names, Census ZCTA-to-county table for ZIP codes

## Known limits

- Drug prices are the median across California plans, not each plan's own price.
- Help with costs (Extra Help, Medi-Cal and similar) is not modelled.
- Only 30-day retail fills are estimated.
- The $35 insulin cap is fixed in `build/app.html`.

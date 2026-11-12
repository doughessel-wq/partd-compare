# California Part D Compare

A single-page tool that estimates 2027 Medicare Part D costs for California plans.

- `index.html` is the finished app, with all data embedded. Open it in a browser or upload it to any static web host.
- `build/app.html` is the page template (layout, questions, cost engine).
- `build/net.py` extracts California pharmacy networks from the CMS monthly file.
- `build/npi.py` looks up pharmacy names in the CMS provider registry.
- `build/data.py` combines everything and writes `index.html`.

The build scripts were written for a one-off working directory and still need their file paths tidied into one repeatable command.

## Data sources

- CMS Monthly Prescription Drug Plan Formulary and Pharmacy Network Information, 2027 (data.cms.gov)
- CMS Quarterly Prescription Drug Plan Formulary, Pharmacy Network, and Pricing Information, 2026 Q3 (data.cms.gov)
- CMS 2027 Star Ratings data tables (cms.gov)
- NLM RxNorm (drug names), CMS NPI Registry (pharmacy names), Census ZCTA-to-county table

Estimates only. Not affiliated with Medicare.gov.

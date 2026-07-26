# Sampling methodology — research grounding (community practice + SOTA)

Status: RESEARCH SYNTHESIS 2026-07-20, input to the open sampling-methodology
brainstorm (goals discussion → team options page). Four parallel research
sweeps: (1) mass-digitization program QA practice, (2) WCAG conformance
evaluation + legal drivers, (3) OCR-evaluation research SOTA, (4) statistical
acceptance-sampling frameworks. Full agent reports live in the session
transcript; this file preserves the load-bearing findings and citations.

## 1. What peer programs actually do

**No major program runs a numeric OCR-accuracy acceptance gate on production
deliverables.** Verified against primary sources:

- **NDNP/Chronicling America**: QA is structural/format validation (JHOVE,
  checksums, ALTO conformance) — no OCR accuracy percentage anywhere in the
  2026–28 Technical Notes. The newer NDNP-Open-OCR reprocessing effort
  measures improvement by a proxy (unique-word-count reduction per batch),
  not ground-truth CER. (loc.gov/ndnp/guidelines/NDNP_202628TechNotes.pdf;
  github.com/LibraryOfCongress/ndnp-open-ocr)
- **HathiTrust**: no documented protocol; member libraries "rely on sampling
  pages... or automated metrics," unspecified. Its 2016 QASWG charge is the
  one primary-source instance of a major program naming "quality fitness for
  print disabled users with respect to OCR accuracy" as a distinct dimension
  — never operationalized. (hathitrust.org/qaswg_charge)
- **Dutch KB**: the most fully specified protocol found — 2,000-page GT set,
  rekey vendor held to 99.95% (paper) / 99.5% (microfilm) with per-batch
  random-paragraph spot checks; stratified by era with deliberate exclusions.
  But it exists for engine benchmarking/research, not corpus acceptance.
  (lab.kb.nl/dataset/historical-newspapers-ocr-ground-truth)
- **Europeana Newspapers/IMPACT**: shared GT repository (PRImA), Aletheia
  tooling, bag-of-words metrics, per-language reporting (93.1%→32.7%) —
  workflow validation, not acceptance gating. (europeana-newspapers.eu Final
  Report 2015)
- **Trove/NLA**: batch sample QC exists; size/threshold unpublished. Targeted
  structural-field rekey (titles + first four lines per article, ~99%).
- **Tanner, Muñoz & Ros 2009** (the team's own precedent, confirmed at
  dlib.org/dlib/july09/munoz/07munoz.html): ~1% of 2M+ pages; two best-case
  100-word zones per sampled page; double-rekeyed GT (≥99.98%); four-tier
  metrics — character 83.6%, word 78%, significant-word 68.4%. Purpose:
  retrospective collection assessment for program planning, not a gate. Still
  among the most rigorous designs surveyed.

The only hard contractual accuracy floors found anywhere apply to **ground-
truth rekey production**, not to OCR output: KB (above); U-Michigan TCP
(~50k books, 99.995% spec, 5% in-house proofread sample per book,
forced/unforced error distinction, rework on failure — dhanswers.ach.org
firsthand account).

## 2. The legal frame (who is asking)

- **DOJ ADA Title II rule**: WCAG 2.1 AA at 28 CFR 35.200. **Compliance
  deadline extended 12 months by Interim Final Rule effective 2026-04-20**
  (FR doc 2026-07663): large entities **April 26, 2027**; small April 26,
  2028. Formal APA amendment, not enforcement discretion; DOJ says it "fully
  anticipates implementing... at the new deadline." Comment period closed
  June 2026 — monitor, don't treat as immovable.
- **Sampling can never certify.** WCAG-EM (w3.org/TR/WCAG-EM/): sampled
  evaluation licenses only a statement of *likely* conformance for sampled
  scope — "conformance claims cannot be made for entire websites based upon
  the evaluation of a selected sub-set." Sample = structured sample covering
  templates/functionality + 10% random on top; explicitly page/template
  oriented, so translating to a 93k-object repository is a novel move UMD
  must define and defend.
- **Archived-content exception (28 CFR 35.201(1))** — four conditions; the
  killer is #4, "dedicated area clearly identified as being archived." ALA /
  Scholarly Kitchen community consensus (contested, not DOJ-adjudicated): a
  unified promoted Digital Collections portal likely does NOT qualify
  wholesale. Counsel's call; not a foundation for the sampling design.
  Preexisting-document exception is PDF/Office formats only.
- **Remediation on request** is legally grounded (effective-communication
  duty, 28 CFR 35.160, survives every exception) and widespread (UNC ~1-week
  turnaround; MSU; U-Mich; OSU building bulk service) — but it is the
  *reactive backstop*, not a substitute for proactive conformance on
  in-scope content.
- **Defensible posture shape** (synthesized; no sector template exists):
  scoped statement + documented sampling methodology + likely-conformance
  claim for sampled scope + accessible-format request channel + remediation
  roadmap. Campus ADA offices would treat a statistical protocol as novel
  evidence to justify, not established practice to cite.

## 3. The methods toolbox (SOTA)

**Metrics.** OCR-D canonical CER = (i+s+d)/(i+s+d+c), per-page and
per-document (ocr-d.de/en/spec/ocrd_eval.html). CER/WER are NOT portable
across tools (normalization + dinglehopper's undocumented confusables list —
Neudecker HIP'21 survey, DOI 10.1145/3476887.3476888). Flexible Character
Accuracy (Clausner et al., PRL 131, 2020) exists for reading-order-heavy
layouts. **Japanese: CER only** — NDL's own NDLOCR-Lite reports CER (avg
0.268); WER is undefined for unsegmented text; report CER with an explicit
WER-omitted note. Significant-word/entity-weighted accuracy remains OPEN
research (Jaud et al., JCDL 2025) — the roadmap metric is a contribution,
not catch-up. LLM-as-judge for OCR QA: not mature; revisit after ICDAR 2026
HIPE-OCRepair.

**Ground truth.** Rekeyed GT needs its own audit — vendor 99.95% claims are
typically unaudited; Haaf & Wiegand (JTEI, journals.openedition.org/jtei/739)
provide the error-classification method; DTA's own stratified audit (7,208
pages, 22 proofreaders) found 99.9909% overall varying by era. Anchor
numbers: **TCP 5% audit-of-rekey**; **Transkribus ~500 random lines** for a
project-level accuracy figure (help.transkribus.org/computing-accuracy).
**Zone/partial-page GT validity is an evidentiary gap** — no study validates
excerpt GT as equivalent to full-page GT; the 2009 zone design (best-case
zones, at that) is an assumption needing its own small validation if reused.

**GT-free quality estimation.** Lexicality/dictionary scoring (Alex & Burns,
DATeCH 2014) and engine-confidence triage (one published system bypassed
manual inspection for 41% of documents) are precedented mechanisms. A named
"GT-free triage + sampled-GT calibration" methodology does NOT exist in the
literature — genuine contribution space.

**Statistics.** FADGI and Metamorfoze are image-only; nothing borrowable for
text. Two distinct tools, matched to two distinct jobs:
- *Estimation* (report a corpus/stratum error rate): two-stage cluster
  sampling; variance inflated by design effect DEFF ≈ 1+(b−1)ρ; no published
  OCR intraclass correlation exists — **a pilot (~20–30 objects × 3–5 pages,
  stratified) measuring variance components is what prices all future
  samples**, and would itself be citable. Stratify by material type/era
  (DTA evidence). Prefer more objects × fewer pages unless the pilot says
  otherwise.
- *Accept/reject* (is this batch above threshold): ANSI/ASQ Z1.4 / ISO 2859
  AQL plans (lot, code letter, Ac/Re, switching rules — TCP ran an artisanal
  version); **SPRT** decides obviously-good/bad batches with 30–50% fewer
  pages and can be operated by students plotting cumulative errors against
  precomputed boundary lines; **skip-lot/CSP** for cheap ongoing surveillance
  of accepted pipelines. No library precedent for SPRT/CSP in text QC —
  another first if adopted.

## 4. The recurring meta-finding

All four sweeps independently concluded: **OCR QA sampling designed for
accessibility remediation at collection scale is undocumented territory.**
No acceptance thresholds in program practice, no WCAG-EM translation for
object repositories, no published DEFF/ICC for OCR errors, no named
triage-then-calibrate methodology, no sector conformance-statement template.
A small, documented, statistically honest methodology from UMD would be
novel practice for the sector — continuous with the 2009 paper's lineage.

## 5. Implication for the goals discussion

Certification-by-sampling does not exist (WCAG-EM doctrine), so the three
candidate goals stop competing and become **layers of one architecture**:

1. **Triage** (~48k existing OCR): GT-free scoring (lexicality/confidence)
   over everything computable, calibrated by sampled rekeys graded in
   dpi-eval.
2. **Estimate** (per stratum): stratified two-stage samples sized by
   pilot-derived variance components → honest "likely conformance"
   statements per collection area.
3. **Gate** (new OCR from iiif_ocr etc.): SPRT/AQL batch acceptance operated
   by students with dpi-eval; skip-lot surveillance once pipelines earn
   trust.
4. **Document** (compliance posture, April 2027): WCAG-EM-shaped statement —
   scope + methodology + likely-conformance + request channel + roadmap.
   The methodology document and dpi-eval reports ARE the evidence.

The team's decision is therefore sequencing and investment across layers,
not choosing one goal — with the pilot's statistical job now precise:
measure variance components and rekey cost per page to price layers 2–3.

## Verification cautions carried forward

- Trove sample size/threshold and its "2013 independent research" figure:
  unverified secondhand.
- KB "0.17% of collection": search-synthesis only.
- Confidence-triage "41%" paper: venue/year unconfirmed — verify before
  formal citation.
- NER-degradation figures (F1 90→60% as CER 8→20%): secondary-source, check
  before citing.
- ARL Title II implications PDF (arl.org, Oct 2024): READ 2026-07-20 (Trevor
  supplied the PDF). Confirms our exceptions analysis; ARL's own words: "no
  specific guidance on how libraries should approach meeting the
  requirements," library examples in the rule "do not align with research
  libraries' digital environment." Recommends exception-framework as a
  prioritization tool run by a cross-functional team (legal/ADA/e-resources/
  IT/digital collections) with a blank analysis chart (p.13); worked example
  is licensed e-resources ONLY — legacy digitized content and special
  collections are listed as categories but never analyzed. Undue-burden/
  fundamental-alteration lever noted for hard material (language-expertise
  example — relevant to the Japanese books). Expects Dept of Ed §504 NPRM on
  the same exception model. Requires WCAG 2.1 June 2018 version specifically.
  Predates the 2026 deadline extension.

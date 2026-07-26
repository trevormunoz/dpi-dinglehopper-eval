# Item 8 targets: real IIIF manifests

QA item 8 — browser mode against a IIIF session — was deferred for want of a
manifest neither we nor an agent wrote. These are real, openly reachable
manifests from UMD's own collections, verified against `parse_manifest` at
`981a6d1`+ on 2026-07-26.

This is now the highest-value manual test left: **R2-C1 and R2-S2 both lived in
the manifest parser**, and every manifest exercised so far was written by us.

## Prerequisite: the User-Agent override

UMD fronts `iiif.lib.umd.edu` with a WAF that filters on `User-Agent`. Without
the override every fetch fails with `HTTP 400`:

```bash
export DPI_EVAL_USER_AGENT='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'
```

Measured 2026-07-26 — `Mozilla/5.0 (Macintosh…)` → 200; `Python-urllib/3.11`
→ 400; `dpi-eval/0.1.0` → 400; no User-Agent at all → 403. The honest value is
the default and is *also* rejected, which is why the override exists.

## URL shape

```
https://iiif.lib.umd.edu/manifests/<fcrepo-id>/manifest
```

`<fcrepo-id>` is the colon-delimited id from a `digital.lib.umd.edu` item URL.
The bare UUID 400s as "not a valid IIIF identifier". Percent-encoded colons
also work.

To find more, the search app has a JSON API that returns the manifest id and an
OCR flag directly:

```
https://digital.lib.umd.edu/api/search/fcrepo_search?q=AFL-CIO
```

Useful fields per result: `iiif_manifest__id`, `has_ocr__facet`
(`"Has OCR"`), `object__title__display`, `object__format__label__display`, and
`iiif_thumbnail_sequence__uris` (its length is the page count).

## Paged-text targets — recommended

All from *Advancing Workers' Rights in the American South* (the AFL-CIO Civil
Rights Department records, `https://digital.lib.umd.edu/awr`), format "Records
(documents)", and all flagged **Has OCR** — so vendor OCR exists to grade the
transcription against, which is the whole point of the tool.

| Pages | Title | fcrepo id |
|---|---|---|
| 6 | AFL-CIO Labor Studies Center, 1975 | `fcrepo:dc:2023:1:b3:7f:3e:17:b37f3e17-f230-4da8-a472-e95584112ebd` |
| 3 | AFL-CIO Public Service Program | `fcrepo:dc:2023:1:60:f6:ca:da:60f6cada-5620-47cb-a4d9-65a6ca5c0d4f` |
| 2 | AFL-CIO Free Trade Union News | `fcrepo:dc:2023:1:aa:1a:88:d0:aa1a88d0-54e2-42df-8f87-8839ca82f696` |

**Start with the 6-page one.** Verified end to end:

- `parse_manifest` returns 6 canvases, stems `p0000-page-1` … `p0005-page-6` —
  0-based indices with 1-based labels, which is the alignment R2-S2 was about.
- Presentation **v2** (`sc:Manifest`, `sequences[0].canvases`, `resource.@id`),
  so this exercises the v2 branch, not v3.
- Image service reports **level2**, `3324 x 4324`, and supports
  `sizeByConfinedWh` — the editor's `full/!1200,1200/0/default.jpg` returns a
  922x1200 JPEG (125 KB) and the lightbox's `full/max/…` returns the full
  3324x4324 (1.3 MB).

Larger paged items exist in the same collection if a bigger sample is ever
wanted — *AFL-CIO Convention, 1969* is 183 pages, *Mississippi AFL-CIO,
1962-1969* is 282. Page selection at create means a long document is usable
without transcribing all of it.

## Photograph targets — parser exercise only

Multi-canvas but almost no text, so CER/WER from these would be meaningless.
Useful only for testing ingest and canvas indexing.

| Canvases | Title | fcrepo id |
|---|---|---|
| 9 | Protesters picketing to desegregate Glen Echo Park | `fcrepo:dc:2023:1:de:15:c6:58:de15c658-2f2f-4e24-9573-4f53773639e4` |
| 2 | MLK on the picket line, Scripto Strike | `fcrepo:dc:2023:1:f1:9c:5d:0b:f19c5d0b-d520-4915-b30b-877e8de9d116` |
| 2 | March on Washington for Jobs and Freedom | `fcrepo:dc:2023:1:55:8b:59:7b:558b597b-823c-43cf-b261-689b0d0c6366` |

## What to watch during the run

- Whether the page images render in the **editor** — WKWebView sends its own
  Safari User-Agent for `<img>` loads, so the WAF should pass them even though
  the Python-side manifest fetch needed the override. If images fail while the
  manifest succeeded, that asymmetry is the finding.
- Whether canvas order in the queue matches the document's page order.
- The `has_ocr` flag means real OCR exists upstream, but this tool does not
  fetch it — you still supply the OCR folder yourself at the grade step.

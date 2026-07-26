# Known residuals

Real defects, deliberately not fixed, each recorded with why it was left and
what decision it needs. Everything here was rated **minor** by the round-2 PAR
reviewers (`2026-07-26-par-review-round2.md`) — none blocks use, corrupts a
score, or loses work.

Opened 2026-07-26 after the round-2 fix-up. The critical and serious findings
from that review are all fixed; these are what was consciously left.

## 1. `_safe_url` allows plain `http://`

`src/dpi_eval/pages.py:_safe_url`

Page image URLs come from whatever IIIF manifest the user points at, and
`http://` is in the accepted-scheme tuple. So a manifest can make the editor
load page images unencrypted: observable on the network, and alterable in
transit. The altered-image case is the one that matters in principle, because
the image *is* the artefact being transcribed — a tampered image corrupts
ground truth at the source.

**Why it is still open:** some real institutional IIIF servers are http-only.
Refusing http could block a legitimate collection.

**Decision needed:** whether any collection we actually intend to use is
http-only. If none is, refuse http and this becomes a two-line change. If some
are, the fallback is to allow http but surface it in the UI, so a student can
see that a page arrived unencrypted.

## 2. The manifest redirect guard checks only the scheme, not the destination

`src/dpi_eval/iiif.py:_NoInsecureRedirectHandler.redirect_request`

The guard refuses a redirect to `http://`, which was the original fix and
holds. It does not constrain *where* an `https://` redirect points, so a
hostile manifest server can redirect the fetch to an address only reachable
from inside the network — a private-range host, link-local metadata
(`169.254.169.254`), or loopback — and the app fetches it and renders the
response. That is server-side request forgery: using a trusted program to
reach things the caller could not reach directly.

The handler's docstring frames it as the SSRF fix, which overstates what it
does. Worth correcting when the code is.

**Why it is still open:** the fix is a rule about which addresses are
off-limits, normally RFC1918 (`10/8`, `172.16/12`, `192.168/16`), link-local
(`169.254/16`) and loopback, applied *after* DNS resolution so a name that
resolves inward is also caught.

**Decision needed:** whether our real collection servers live on internal
addresses. On a university network they plausibly do, and a blocklist written
without knowing that would break legitimate use.

## 3. `POST /transcribe/sessions` answers 422 rather than 403

`src/dpi_eval/web.py`

FastAPI validates a route's declared parameters before the function body runs,
and the token check lives in the body. A request with no token *and* a missing
required field is rejected for the missing field — with an error naming the
fields it expected — before authorisation is considered.

**Not a bypass.** A wrong token still gets 403, and the shape-fault half of
R2-S1 (a token of the wrong type crashing the gate) is fixed on every route.
What remains: an unauthenticated caller can learn the API's field names, and
the body is fully read and buffered before rejection.

**Why it is still open:** the proposed fix moves the check into a FastAPI
dependency, on the premise that dependencies resolve before the dependant's own
parameter validation. **That premise is unverified.** It would touch all nine
mutating routes, which is too much surface to change on an unchecked
assumption.

**Decision needed:** verify the ordering claim first — a single throwaway route
with a `Depends` token check and a missing required field settles it. Only
worth the refactor if it holds.

## 4. A failed grading run can leave a partial run directory

`src/dpi_eval/web.py:_run_and_register`

The function creates `run-NNN/` and then copies the ground-truth and OCR sets
into it. An `OSError` partway through (disk full, permissions) leaves a run
directory with some files and no `result.json`, which could appear in a run
listing as a broken entry.

The retry-critical half is fixed: R2-S3 means the staged upload now survives a
failed confirm, so nobody has to re-pick a folder.

**Why it is still open:** two coupled decisions. Whether a partial run should
be rolled back or kept as evidence of what failed; and what the function should
raise, since several tests call it directly as a plain helper returning a
`Path`, so switching it to a web-shaped error changes their contract.

## Not residuals

For the record, so they are not re-raised as findings:

- **Manifests whose canvases lack a usable image are rejected, not skipped.**
  Intended. Skipping would shift every later canvas index and silently grade
  one page's transcription against another page's OCR.
- **`/grade` drops an upload with an empty flattened basename while
  `stage_ocr` rejects one loudly.** Both are correct for their site:
  `discover_pairs` surfaces an unpaired file in the `/grade` report, so nothing
  is silently absent from a score, and the staging path has no such backstop.
- **The round-1 and round-2 PAR reports describe unfixed code.** Both are
  dated snapshots. Describing the code as it stood is correct for what they are.

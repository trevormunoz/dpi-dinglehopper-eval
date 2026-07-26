# Deep usability redesign — seeded design cycle (post-pilot)

Status: SEEDED 2026-07-19; scheduled to run after the pilot, designed
against observed student/supervisor use (Trevor's sequencing
decision). Companion to the parked IIIF cycle
(2026-07-19-iiif-brainstorm-parked.md) — the two may merge at the
supervisor-view/image-evidence seam.

## Settled inputs (Trevor, 2026-07-19)

1. **The OCR engine is the graded party.** The student's careful
   rekey IS the ground truth; scores measure machine quality. An
   amber page means the OCR struggled — the student did their job by
   typing faithfully. (Continuous with the 2009 D-Lib framing:
   sampled rekey GT measuring OCR accuracy.) Copy audit at decision
   time found no page actively blaming the transcriber; the ambient
   ambiguity of the word "grade" is in scope here.
2. **Pilot first.** A–D + the clean-and-credible pages ship; this
   cycle designs from real feedback, not guesses.
3. **Organizing frame: two views, two leading questions.** Student:
   "where did this page go wrong?" Supervisor: "is this batch/engine
   trustworthy, and what is systematically confused?" The four deep
   issues below resolve inside that split.

## The four deep issues (all selected by Trevor)

1. **Whose error is it** — direction semantics in every label, band,
   caveat; resolved in principle by settled input 1, cascades into a
   full copy/IA pass per view.
2. **Metrics that mean what they seem** — stop asking students to
   mentally discount layout-inflated raw scores. Candidates:
   layout-normalized scoring mode; the roadmap significant-word
   error rate (proper nouns, numbers, entities — use-relevant for
   discovery and assistive tech). Feasibility flag: entity-aware
   scoring needs NER-ish computation the offline wheelhouse must
   carry — size/complexity to be assessed honestly (the engine fence
   and `import dinglehopper` rule still stand; new analysis would sit
   beside the engine, not inside it).
3. **Diffs at real scale** — dense pages produce highlight walls: no
   error-density overview, no next/previous-difference navigation,
   no anchor from a summary mistake ("e→c ×14") to its occurrences.
   All candidate serve-time enhancements at the wrapper seam.
4. **Student view vs supervisor view** — admit two artifacts (or one
   artifact with two modes). Supervisor view is also where the IIIF
   cycle's image evidence and the --differences mistake tables pay
   off together.

## Evidence base to collect during the pilot

- Which pages students actually open (server logs are local; ask
  supervisors to note behavior instead — no telemetry without a
  deliberate decision).
- Where supervisors take QA decisions from (results page? summary?
  zip?).
- Whether amber/red bands change student behavior, and in which
  direction (the whose-error risk made concrete).
- **Rekey cost, observed (added 2026-07-20):** how long a rekeyed page
  actually takes and how many pages a student completes per sitting —
  measured during the pilot, not estimated. This is one of the two
  numbers that price the sampling methodology.
- **Error clustering, measured (added 2026-07-20):** grade enough
  multi-page objects across material types to estimate how strongly
  error rates cluster within objects (intraclass correlation → design
  effect). No published value exists for OCR; this number sets the
  page-count multiplier for every future sample. See
  docs/superpowers/2026-07-20-sampling-research-grounding.md §3.

# Task 4: family-law transcripts (DRAFT, 2026-10-10)

Status: steps 1 and 2 are done as far as the opinion text allows. Steps 3 to 5 are drafts. Nothing has been sent to any court. A compliance lawyer must review before sending.

## Step 1 and 2: the case list (done, with limits)

File: ~/Kingsfield_Corpus/flcourts/family_law_cases.csv (not in git; data stays local). Built by Verifier/judicial-intel-analytics/pipeline/family_law_filter.py from the 133,111 opinion texts.

Columns: case number, court, date, case style, So. 2d/3d citation (if known), hearing types mentioned, whether the opinion mentions a transcript, why it matched, PDF link.

Result: 10,313 cases flagged as family law. 5,419 have a So. citation. 1,101 opinions mention a transcript.

By court: Supreme Court folder 5,221; 1st DCA 1,312; 4th DCA 1,217; 2nd DCA 903; 5th DCA 842; 3rd DCA 755; 6th DCA 63.

Hearing types mentioned (a case can appear in several): final hearing or trial 8,615; evidentiary hearing 1,479; case management or pretrial 392; adjudicatory or disposition 369; temporary 283; contempt 137; shelter 96.

Limits, stated plainly:
- The match uses the case style and the first 6,000 characters of the opinion. It has not been checked by a person. It likely includes some non-family cases (for example "minor" or "guardianship" in other contexts) and misses some family cases.
- "Opinion mentions a transcript" is read from the opinion text only. It does not show that a transcript was filed in the appellate record. Only the court docket or the clerk can show that. This step is NOT done.
- The Supreme Court folder count (5,221) is high. Check what that folder contains before using the number.

## Step 3: proposal to the Florida courts (draft)

To: the relevant Florida Supreme Court committee and the DCA clerks.

Draft text:

"Kingsfield is building a citation-verification tool for Florida appellate authority. We have assembled a table of Florida appellate decisions since 2008 with their Southern Reporter citations. We would like to test the tool on family-law hearing transcripts. We request de-identified transcripts of family-law trial-level hearings, handled under Fla. R. Gen. Prac. & Jud. Admin. 2.515(d)(2) as amended by AOSC26-12 (effective June 15, 2026). We will share the completed citation table and the cite checker with the court. We will use transcripts only for testing, never for training or publication, and will follow any conditions the court sets. A compliance attorney has reviewed this request. [CONFIRM BEFORE SENDING]"

Before sending, verify: the rule text and AOSC26-12 (from the 2026-10-03 plan, not re-checked today), who the right committee and clerk contacts are, and that the compliance review actually happened.

## Step 4: synthetic sandbox (plan, not built)

Use what we already have: diarized 2nd DCA oral-argument transcripts, opinion passages that describe trial hearings, and a list of Florida Evidence Code (ch. 90) objections. Purpose: testing the pipeline only. No accuracy claims from synthetic data. Note: the existing Gemini diarization is not ground truth (see memory note gemini-diarize-unusable).

## Step 5: Michigan trial-level hearings (not started)

Needs the Michigan court rules and a source for recorded hearings. Not researched yet.

## Needs Aaron

1. Approve or edit the proposal text.
2. Confirm a compliance lawyer will review it.
3. Decide who signs it.

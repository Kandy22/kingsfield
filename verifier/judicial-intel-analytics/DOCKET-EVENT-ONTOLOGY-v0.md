# Docket Event Ontology v0

Companion to *Moneyball for Lawyers — Build Spec v0.1*. Drafted 2026-09-06.

Purpose: turn a free-text PACER docket entry into a typed event with an actor, a disposition, timestamps, and edges to other entries. This is the asset the rest of the metric stack sits on.

Every design choice below was checked against real RECAP entry text pulled from CourtListener, quoted throughout.

## 1. Event taxonomy

Namespaced, three levels deep at most. Start narrow and let the weak-label pass tell you what is missing.

### Party events

Motions, dispositive:
`motion.dispositive.dismiss`, `motion.dispositive.summary_judgment`, `motion.dispositive.judgment_on_pleadings`, `motion.dispositive.default_judgment`

Motions, procedural:
`motion.proc.extend_time`, `motion.proc.continue`, `motion.proc.leave_to_amend`, `motion.proc.pro_hac_vice`, `motion.proc.substitute_counsel`, `motion.proc.withdraw_counsel`, `motion.proc.seal`, `motion.proc.shorten_time`

Motions, discovery:
`motion.disc.compel`, `motion.disc.protective_order`, `motion.disc.sanctions`, `motion.disc.quash`, `motion.disc.examination`

Motions, relief:
`motion.relief.preliminary_injunction`, `motion.relief.tro`, `motion.relief.class_cert`, `motion.relief.remand`, `motion.relief.transfer_venue`, `motion.relief.stay`, `motion.relief.relief_from_stay`

Motions, post-judgment and access:
`motion.post.reconsider`, `motion.post.new_trial`, `motion.post.fees`, `motion.access.ifp`

`motion.access.ifp` earns its own branch. In forma pauperis practice is the highest-signal event class for the pro se work and it is where the Scarlet Letter hypothesis is testable. Observed: *"ORDER GRANTING MOTION TO PROCEED IN FORMA PAUPERIS ON APPEAL AND COLLECTION ORDER re: 21 MOTION for Leave to Appeal in forma pauperis…"*

Non-motion party events:
`pleading.complaint`, `pleading.amended_complaint`, `pleading.answer`, `pleading.counterclaim`, `brief.response`, `brief.reply`, `brief.supplemental`, `notice.appeal`, `notice.removal`, `notice.voluntary_dismissal`, `stipulation`

### Court events

Rulings on motions — the disposition is an attribute, not a separate type. Type is `ruling`, disposition is one of:
`granted`, `denied`, `granted_in_part`, `denied_without_prejudice`, `denied_as_moot`, `withdrawn`, `taken_under_advisement`, `deferred`

The last four matter more than the first two. A motion denied as moot is not a loss; a denial without prejudice is not a merits ruling; a motion taken under advisement has no disposition yet and belongs in the survival model as censored, not as an outcome. Collapsing these into grant/deny is the standard vendor error and it corrupts every downstream rate.

Court events that are not rulings on party motions:
`order.sua_sponte.show_cause`, `order.sua_sponte.dismissal`, `order.scheduling`, `order.referral_magistrate`, `order.report_recommendation`, `order.adopt_rr`, `order.reject_rr`, `order.set_hearing`, `judgment.final`, `case.terminated`, `case.reopened`, `case.stayed`, `case.remanded`, `case.transferred`, `case.converted`

`order.sua_sponte.*` is the SLR metric's entire basis. Capture it precisely.

`order.report_recommendation` versus `order.adopt_rr` is not cosmetic — a magistrate's recommendation is not a ruling, and attributing it to the district judge (or the reverse) mis-assigns the decision. See §4.

### Administrative

`admin.clerk_correction` (from *"Modified on 7/19/2016 (SWM)"*), `admin.fee_receipt` (from *"Filing fee $46, receipt number 0756-3931451"*), `admin.docket_correction`

## 2. Entry schema

Per entry:

- `entry_id`, `docket_id`, `court_id`, `entry_number`
- `event_type` — from §1
- `disposition` — rulings only, from §1
- `date_filed` — the docket's filing date
- `date_signed` — parsed from the text
- `date_entered` — parsed from the trailing `(Entered: …)`
- `actor_role` — `court`, `plaintiff`, `defendant`, `third_party`, `clerk`
- `signer_name`, `signer_id`, `signer_type` — `article_iii`, `magistrate`, `bankruptcy`, `clerk`
- `related_entries` — resolved edges, see §5
- `filer_attorneys` — parsed from trailing `(Lastname, Firstname)`
- `deadlines_set` — list of label/date pairs
- `is_text_only`
- `extraction_method` — `regex`, `weak_label`, `model`
- `confidence`

Never overwrite the source string. Every derived field must be re-derivable from the raw description when the parser improves.

## 3. The three clocks

Three distinct dates appear in one entry and they are routinely conflated:

> *"Order Granting Motion to Shorten (Related Doc # 257). Signed on 12/19/2016. (Gossett, Valerie) (Entered: 12/19/2016)"*

> *"Order Granting Motion to Extend Time (Related Doc # 60). Response Brief due by 11/21/2014. Signed on 11/26/2014. (Gossett, Valerie) (Entered: 11/26/2014)"*

> *"ORDER granting Non-Parties' 16 Motion for Extension of Time… Signed by Magistrate Judge Tim A. Baker on 7/5/2016. (SWM) (Entered: 07/05/2016)"*

Rules:

1. Time-to-ruling = `date_signed` of the ruling minus `date_filed` of the motion. Never the entered date — clerk lag then becomes part of the judge's number.
2. `date_entered` minus `date_signed` is the clerk lag, reported as a court-administration metric, never as a judge metric.
3. When `date_signed` is absent, fall back to `date_filed` and set a flag. Report the fallback rate; a court where it fires often needs its own parser.

Note the second example above: the order granting an extension sets a response deadline *earlier than the signature date*. Retroactive deadlines are real and common. Any deadline logic that assumes monotonic dates will produce negative durations — clamp and flag rather than silently dropping.

## 4. Actor attribution

The signer is embedded in the text and must be extracted, not inherited from the docket's assigned judge:

> *"Ordered by Magistrate Judge Jeff Armistead."*
> *"Signed by Magistrate Judge Tim A. Baker on 7/14/2016."*
> *"(Signed by Magistrate Judge B Janice Ellington)"*

The docket's `assigned_to` is the district judge; a large fraction of orders are signed by a magistrate. Attributing magistrate rulings to the district judge inflates the district judge's volume and contaminates the causal design in §6 of the spec — random assignment applies to the district judge, not to who happened to sign a discovery order.

Resolve `signer_name` to a CourtListener `people` id. Expect name collisions and middle-initial noise (*"B Janice Ellington"*, *"Michael A. O'Hara, III"*). Keep the raw string alongside the resolved id.

Also parse the filing attorney from the trailing paren — *"(Kelley, Daniel)"* — and distinguish it from the clerk initials that occupy the same position on court entries — *"(SWM)"*, *"(pjg)"*, *"(bfm)"*. Heuristic: comma-separated title case is an attorney; bare lowercase or short caps initials is a clerk. Verify against the docket's attorney table rather than trusting the heuristic.

## 5. The motion→ruling edge

The highest-value parse in the system. Observed reference formats:

- `(Related Doc # 296)` — bankruptcy standard
- `(Related Doc # 5 and 8)` — multiple, no second hash
- `(Related Doc 119)` — no hash
- `.(Related Doc # 151)` — leading period, no space
- `(Related Doc # 190)` with a following `(EPD)` clerk block
- `re: 21 MOTION for Leave to Appeal in forma pauperis MOTION to Admit Evidence be Included, 23 MOTION/APPLICATION…, and 24` — district style, multiple targets, one of them bare
- `granting 19 Motion to Appear pro hac vice` — bare inline number
- `Granting Motion for Entry of Default 19 .` — bare trailing number
- `Granting Motions for Leave to Appear Pro Hac Vice for Attorney Ryan M. Spear 48 and for Attorney Margot Loken 49` — two edges, one order

Consequences for the design:

1. The edge is many-to-many. One order can dispose of several motions; one motion can draw several orders. Model it as an edge table, never as a foreign key on the entry.
2. Bare integers are ambiguous with dates, dollar amounts, rule numbers (*"Rule 9019"*, *"Rule 3019(a)"*, *"Local Rule 5-3"*), and statute references. Require validation against entry numbers actually present on that docket before accepting a bare-number edge.
3. **Report edge resolution coverage on every run.** A ruling with no resolved motion is not a data point — it is a hole. A model trained where the edge resolves for a minority of rulings is a model of the entries that happened to be easy to parse.

## 6. Bootstrap labeling

RECAP already carries normalized labels on a meaningful share of entries in the `short_description` field:

> `"Order on Motion to Approve Compromise or Settlement"`
> `"Order on Motion for Authority to Sell or Lease Property"`
> `"Order on Motion to Convert Case from Chapter 11 to Chapter 7"`
> `"Order on Motion for Examination of an Entity"`
> `"Order on Motion to Deem Acceptance of Modified Plan"`

Procedure: seed the label set from populated `short_description` values, map them onto the §1 taxonomy once by hand, train a classifier on the raw `description`, then apply to the majority of entries where `short_description` is empty. Days of work, not months, and it produces a defensible label provenance trail.

## 7. Known traps

**Bankruptcy skew.** A naive sample of RECAP entries returns heavily bankruptcy-flavored text — chapter conversions, cash collateral, relief from stay, proofs of claim. Stratify by court type and nature-of-suit before training, or the ontology will overfit bankruptcy vocabulary and underperform badly on civil dockets, which is where the product lives.

**Coverage is not random.** RECAP entries exist because someone paid to unlock them. Selection operates on both which dockets appear and which documents within them. Model coverage explicitly; validate rates against FJC IDB terminations.

**Entries mutate.** *"Modified on 7/19/2016"*, *"Modified on 11/22/2022 (AnitaM QC MNBD)"*. Version the entry rather than overwriting; a corrected entry is evidence about the court's administration as well as about the case.

**Sealed and restricted entries** create missingness correlated with case type and party sophistication — exactly the correlation that will bias any pro se comparison if left unmodeled.

**Prefixed and agreed orders.** *"(E)Order Granting Motion To Pay"*, *"Agreed Order Granting Motion to Continue/Reschedule"*, *"Final Order Granting Motion To Use Cash Collateral"*. An agreed order is a stipulation the judge signed, not a contested ruling the judge decided. Counting agreed orders as grants inflates every grant rate. Detect and segregate them — this is a one-line regex with a large effect on the headline number.

**Proposed orders are not orders.** *"(Attachments: # 1 Text of Proposed Order Granting Motion)"* is a party filing containing the phrase "Order Granting Motion." Any keyword-matching approach will misclassify it. Attachment context must be parsed before disposition.

## 8. Validation before modeling

Ship these three before any metric:

1. Parse-coverage dashboard: share of entries typed, share of rulings with a resolved motion edge, share with a parsed signature date, by court and year.
2. A hand-audited random sample of several hundred entries with per-class precision and recall, stratified by court type.
3. Negative controls: agreed orders, proposed orders, and denials-as-moot each correctly excluded from grant-rate numerators, verified by hand.

If these three do not hold, no metric downstream is worth computing.

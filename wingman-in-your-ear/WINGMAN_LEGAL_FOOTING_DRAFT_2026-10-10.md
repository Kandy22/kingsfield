# Wingman legal footing (DRAFT, 2026-10-10)

Status: draft for Aaron and a lawyer. Not legal advice. Nothing has been filed or sent.

Sources: KINGSFIELD_MASTER_REF (1).md sections on Morgan v. V2X and on the ADA (section 13), and the Oct 3 task list item 5.7. I checked one thing today: Morgan v. V2X exists. A later District of Colorado filing (Dunn v. LexisNexis, Aug. 31, 2026) cites it. I did not re-read the Morgan opinion itself.

## 1. Facts the request must state truthfully

Your master reference says Wingman "does not record or transmit proceedings externally." The current code does not match that:

- wingman-demo streams live courtroom audio to Google Gemini Live.
- When cues are on, the transcript text goes to Jev through OpenRouter.
- wingman-demo/logs/ holds real hearing text on the Mac.
- I found no code that deletes sessions after 30 days. The master reference says transcripts are destroyed within 30 days.

Until that changes, the request must say that audio is processed by named third-party AI providers. It must not say that nothing leaves the device. A false statement to a court is worse than a denied request.

## 2. AI provider check (Morgan protective-order standard)

The standard, as quoted in the master reference: the AI provider must be contractually prohibited from (1) storing or using inputs to train or improve its model, and (2) disclosing inputs to any third party except where essential to deliver the service.

Check each provider before any real hearing. Keep the written terms on file.

- Google Gemini (live audio). Use only a paid or enterprise tier whose terms say inputs are not used for training. Do not use the free tier, whose terms allow use of your inputs to improve Google's products. Record which key and which terms are used.
- OpenRouter, and TypeSafe behind it (Jev cues). Get both companies' retention and training terms in writing. OpenRouter passes requests on to the model provider, so both sets of terms matter.
- Morgan also held, per the master reference, that the identity of the AI tool is not protected. Be ready to name the tools if asked.

## 3. ADA accommodation request (draft)

The ADA covers a person with a disability. "Needs legal help" is not a disability. This request works for a user who has one. For Aaron, that is blindness. Other users need their own basis.

In Florida, check Fla. R. Gen. Prac. & Jud. Admin. 2.540 (requests by persons with disabilities) and the circuit's ADA coordinator. Also check the judge's or the circuit's order on electronic devices. I have not checked these rules today.

Draft text:

"I am a party in this case and I am blind. I request permission to use a personal assistive device during the hearing on [date]. The device is my phone and one earpiece. It listens to the proceedings and shows or speaks short prompts to me, such as that a question is waiting for my answer. It does not broadcast, livestream or publish the proceedings. To work, it sends audio to [provider names] for real-time processing under terms that prohibit training on, or sharing, my inputs. Copies of those terms are attached. The court does not need to provide anything, and there is no cost to the court. I will turn the device off at any time the court directs."

Attach the provider terms from section 2.

## 4. What must change in code before a real hearing

1. Turn off hearing-text logging by default, or delete logs on a fixed schedule. The 30-day deletion has to exist before anyone claims it.
2. Show the advisory banner on every cue. This is already done in CueCards.tsx.
3. Show a clear "cues off" state, so the user does not rely on silence. This is already done.
4. Record which providers and tiers are used for each session.

## 5. Open questions for the lawyer

- Is real-time processing by a third-party provider "recording" under the court's device rules or Florida's interception statute, ch. 934?
- Does Morgan, a federal magistrate's order under Federal Rule 26(b)(3), carry weight in a Florida state family court? Florida has its own work-product rule, Fla. R. Civ. P. 1.280.
- Is a cue such as "possible objection: hearsay" legal advice, which raises the unauthorized-practice question?

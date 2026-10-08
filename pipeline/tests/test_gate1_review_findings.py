"""Findings from the final adversarial review of task gate1-draft-mode.

Gaps the existing suite does not cover, found by reading the code (items 3 and 4 are the route tests at the
bottom of this file: /crew/chat and /council release model text with no Gate 1 at all):

  1. check_text() cleans the draft before extraction (_clean_draft). The cleaner removes HTML tag
     ATTRIBUTES and the CONTENT of HTML comments. The frontend renders model output with
     react-markdown + rehype-raw, so an attribute value (title / alt tooltip, broken-image alt text)
     reaches the user, and HTML written inside a markdown code fence is shown to the user as literal
     text, comment and attributes included. A fabricated Florida citation held in one of those places
     is dropped by the cleaner, so check_text returns [] and the draft is released with no veto.
  2. backend/src/crew/researcher.ts: Phase 3 asks the model for free-text holding / relevance notes
     and returns them in ResearcherOutput (and returns the raw model-proposed `searchPlan` strings),
     but no Gate 1 text check is applied to that model-written text. The authorities themselves are
     built from CourtListener / local-index data and are safe; the prose around them is not.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate1_fixture as fx  # noqa: E402
import draft_harness as dh  # noqa: E402

FAB = "Doe v. Roe, 999 So. 3d 999 (Fla. 2015)"
BACKEND_SRC = fx.REPO / "backend" / "src"

# Findings 1 and 2 (the /api/crew/chat route, the /api/council route) are live tests. Finding 3 (runResearcher's model
# text) is fixed at the route, not inside researcher.ts; see SKIP_REASON and RunResearcherReachesOnlyAGate1Route below.
SKIP_REASON = (
    "OPEN, needs a user decision (finding 3): runResearcher returns ungated model text (the Phase 3 holding/relevance "
    "notes and the raw searchPlan strings). The fix is at the route: runResearcher -> runCrew -> POST /crew/chat, which "
    "runs Gate 1 over everything it sends from runCrew's output (enforced by "
    "RunResearcherReachesOnlyAGate1Route.test_every_runresearcher_caller_chain_ends_in_a_gate1_route). researcher.ts is "
    "outside the builder's write paths, so this in-function assertion cannot pass. The user must decide: accept the "
    "route-level coverage (then retire this test) or change researcher.ts so runResearcher gates its own text."
)


def py_text(draft):
    return fx.py_check_text(draft, dh.get_draft_fixture().db)


# Each draft puts a fabricated Florida cite in text the user can see (tooltip, alt text, code block) but that
# _clean_draft discards. Surrounding prose is plain so the only citation in the draft is the fabricated one.
HIDDEN_BUT_VISIBLE = {
    "html_title_attribute": 'The rule is settled. <span title="%s">hover here</span>' % FAB,
    "html_anchor_title": 'The rule is settled. <a href="https://example.com" title="%s">the case</a>' % FAB,
    "html_img_alt_attribute": 'The rule is settled. <img src="missing.png" alt="%s">' % FAB,
    "html_abbr_title_single_quotes": "The rule is settled. <abbr title='%s'>see note</abbr>" % FAB,
    "md_link_title": 'The rule is settled. [the case](https://example.com "Doe v. Roe, 999 So. 3d 999")',
    "md_image_title": 'The rule is settled. ![chart](https://example.com/x.png "Doe v. Roe, 999 So. 3d 999")',
    "comment_shown_in_code_fence": "The rule is settled.\n\n```html\n<!-- %s -->\n```\n" % FAB,
    "attribute_shown_in_code_fence": 'The rule is settled.\n\n```html\n<span title="%s">x</span>\n```\n' % FAB,
    # Entity-encoded markup is plain visible text to the reader (the entity decodes to a literal "<"), but the
    # cleaner decodes entities first and then strips the "tag", attribute and all.
    "entity_encoded_tag_visible_as_text": 'The rule is settled. &lt;span title="%s"&gt;x&lt;/span&gt;' % FAB,
    "entity_encoded_comment_visible_as_text": "The rule is settled. &lt;!-- %s --&gt;" % FAB,
}


class VisibleTextTheCleanerDrops(unittest.TestCase):
    maxDiff = None

    def test_fabricated_florida_cite_in_attribute_or_code_shown_html_is_never_silently_dropped(self):
        for name, draft in HIDDEN_BUT_VISIBLE.items():
            with self.subTest(variant=name):
                results = py_text(draft)
                verdicts = [r.verdict for r in results]
                self.assertTrue(
                    results,
                    "SILENTLY DROPPED: _clean_draft discarded text the user can see, so a fabricated Florida "
                    "citation is released with no result at all: %r" % draft)
                self.assertIn("veto", verdicts, "no veto: %r -> %r" % (draft, results))
                self.assertNotIn("pass", verdicts, "fabricated cite passed: %r" % draft)
                for r in results:
                    if r.verdict == "fall_through":
                        self.assertNotRegex(r.text, r"(?i)\bso\b\.?|weekly",
                                            "fabricated Florida cite routed to CourtListener: %r -> %r" % (draft, r))

    def test_a_real_cite_in_the_same_places_is_still_checked_not_dropped(self):
        # Control for the fix: whatever extraction is added must keep a REAL record passing and must still
        # veto the same text with the wrong caption. A gate that vetoes everything would fail the first half.
        real = 'The rule is settled. <span title="Smith v. State, 100 So. 3d 200 (Fla. 2012)">hover</span>'
        wrong = 'The rule is settled. <span title="Hernandez v. Walmart Stores, Inc., 100 So. 3d 200 (Fla. 2012)">hover</span>'
        got_real = py_text(real)
        self.assertTrue(got_real, "real cite in a title attribute silently dropped")
        for r in got_real:
            self.assertIn(r.verdict, ("pass", "veto"), repr(r))
            if r.verdict == "pass":
                self.assertEqual(r.cluster_id, fx.SMITH)
        got_wrong = py_text(wrong)
        self.assertTrue(got_wrong, "wrong-caption cite in a title attribute silently dropped")
        self.assertNotIn("pass", [r.verdict for r in got_wrong], repr(got_wrong))


# ───── Researcher: model-written text returned without a Gate 1 text check ─────

def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def _run_researcher_body(code):
    m = re.search(r"export\s+async\s+function\s+runResearcher\b", code)
    if not m:
        return None
    rest = code[m.start():]
    nxt = re.search(r"\n(?:export\s|interface\s|function\s|async\s+function\s)", rest[10:])
    return rest if not nxt else rest[: nxt.start() + 10]


class ResearcherModelText(unittest.TestCase):
    GATES = r"\b(?:localGate1Text|verifyDraft|verifyDraftForSse)\s*\("

    def test_model_written_text_is_gated_before_runresearcher_returns_it(self):
        self.skipTest(SKIP_REASON)
        path = BACKEND_SRC / "crew" / "researcher.ts"
        code = _code(path.read_text(encoding="utf-8"))
        body = _run_researcher_body(code)
        self.assertIsNotNone(body, "runResearcher not found")
        completions = [m.start() for m in re.finditer(r"\bcompleteText\s*\(", body)]
        self.assertTrue(completions, "test needs updating: runResearcher no longer calls the model")
        ret = body.rfind("return {")
        self.assertNotEqual(ret, -1, "runResearcher has no final return")
        gates = [m.start() for m in re.finditer(self.GATES, body)]
        later = [g for g in gates if completions[-1] < g < ret]
        self.assertTrue(
            later,
            "runResearcher returns model-written text (the Phase 3 holding/relevance notes via "
            "applyRelevanceNotes, and the raw model-proposed `searchPlan` strings) without running Gate 1 over "
            "it. Only the authorities are verified. Run the text through localGate1Text()/verifyDraft(), or stop "
            "returning model prose and unverified citation strings from this role.")
        # and the gate result must be acted on, not computed and ignored
        self.assertRegex(body[later[0]:ret], r"['\"]veto['\"]|hasVetoes|vetoed",
                         "the Gate 1 result over the model's text is never acted on")


# ───── Routes that release model output with no Gate 1 at all ─────
#
# Constraint A: no generative model output may bypass Gate 1. The Gate1Ordering tests only look for
# citationLookup( call sites and for the Researcher, so they cannot see a route that never verifies anything.
# routes/index.ts says "The hallucination guard middleware is applied to /api/crew/chat so any cite the Crew
# produces gets verified before it leaves the server." Nothing applies it: /crew/chat is an SSE handler that writes
# content_delta events straight from runCrew()/completeText(), and hallucinationGuard only wraps res.json anyway.
# /council returns advisor, reviewer and chairman text from five models with res.json(out), also unverified.
# (chat.ts / projectChat.ts stream-before-verify is the separately tracked W2-W4 and is not asserted here.)

ROUTES = BACKEND_SRC / "routes"
GATE_CALL = r"\b(?:verifyDraftForSse|verifyDraft|localGate1Text)\s*\("


def _handler(code, start_pat, end_pats):
    m = re.search(start_pat, code)
    if not m:
        return None
    rest = code[m.start():]
    ends = [e.start() for e in (re.search(p, rest[20:]) for p in end_pats) if e]
    return rest if not ends else rest[: min(ends) + 20]


class RoutesThatReleaseModelTextMustRunGate1(unittest.TestCase):
    def _index(self):
        return _code((ROUTES / "index.ts").read_text(encoding="utf-8"))

    def test_crew_chat_runs_gate1_over_the_reply_it_streams(self):
        h =_handler(self._index(), r"r\.post\(\s*'/crew/chat'", [r"\n  // ──", r"\n  r\.(?:post|get|put|delete)\("])
        self.assertIsNotNone(h, "POST /crew/chat handler not found")
        self.assertRegex(h, r"\brunCrew\s*\(|\bcompleteText\s*\(", "test needs updating: /crew/chat no longer calls a model")
        gate = re.search(GATE_CALL, h)
        self.assertIsNotNone(
            gate,
            "POST /crew/chat streams model-written text (the Team Lead reply, the specialist / opposition-map / "
            "IP-triage replies whose starred_cases and their_authority fields are model-written citations, the "
            "direct completeText fallback, and the LLM-written `relevance` on each citation chip) with no Gate 1 "
            "check at all. Run verifyDraftForSse() (or localGate1Text()) over the reply and emit the verdicts.")
        self.assertRegex(h[gate.start():], r"['\"]verification['\"]|hasVetoes|vetoed",
                         "/crew/chat computes a Gate 1 result but never sends it")

    def test_council_runs_gate1_over_the_text_it_returns(self):
        h =_handler(self._index(), r"r\.post\(\s*'/council'\s*,", [r"\n  r\.(?:post|get|put|delete)\("])
        self.assertIsNotNone(h, "POST /council handler not found")
        self.assertRegex(h, r"\brunLLMCouncil\s*\(", "test needs updating: /council no longer runs the council")
        gate = re.search(GATE_CALL, h)
        self.assertIsNotNone(
            gate,
            "POST /council returns advisor, reviewer and chairman text from five models (framedQuestion, "
            "advisors[].text, reviewers[].text, chairmanVerdict) with res.json(out) and no Gate 1 check. A "
            "fabricated citation in any of them is released, and persisted to llm_council_sessions, unverified.")
        self.assertRegex(h[gate.start():], r"['\"]verification['\"]|hasVetoes|vetoed|__verification",
                         "/council computes a Gate 1 result but never returns it")

    def test_no_route_file_runs_a_model_pipeline_without_a_gate1_call(self):
        offenders = []
        for p in sorted(ROUTES.rglob("*.ts")):
            code = _code(p.read_text(encoding="utf-8"))
            if re.search(r"\brun(?:Crew|LLMCouncil|Researcher)\s*\(", code) and not re.search(GATE_CALL, code):
                offenders.append(str(p.relative_to(fx.REPO)))
        self.assertEqual(
            offenders, [],
            "route files that run the Crew / Council / Researcher and never call verifyDraft, verifyDraftForSse or "
            "localGate1Text: %r" % offenders)


# ───── Finding 3, route-level coverage: runResearcher -> runCrew -> a route that gates before it writes ─────
#
# researcher.ts is not changed. runResearcher returns ungated model prose (Phase 3 holding/relevance notes, raw
# searchPlan strings), so the only thing standing between it and a user is the route that sends runCrew's output.
# This test fails the moment that chain gets a new link, or a link stops gating:
#   1. runResearcher is mentioned only in crew/coordinator.ts (and defined in crew/researcher.ts), and every call to it
#      sits inside runCrew.
#   2. runCrew is called outside crew/ only from route handlers (r./router./app. get/post/...) that run a Gate 1 call
#      (verifyDraftForSse / verifyDraft / localGate1Text, or an export of middleware/hallucination_guard.ts that calls
#      one) after the runCrew call and before anything is written to the response, with no further model call after it.
# It is a static check: it cannot prove the string that was gated is the string that is sent. The behavioral proof is
# the chat real-gate cases and whatever route-level test the builder adds.

GUARD_FILE = BACKEND_SRC / "middleware" / "hallucination_guard.ts"
GATE_NAMES = ("verifyDraftForSse", "verifyDraft", "localGate1Text")
ROUTE_REGISTRATION = re.compile(r"(?<![\w.])(?:r|router|app)\.(?:get|post|put|patch|delete|all|use)\s*\(")
WRITE_TO_RES = re.compile(
    r"(?<![\w.])(?:sse|write|writeSse|sendEvent|send|emit)\s*\(|\bres\.(?:write|json|send|end|status|sendFile|type|redirect)\s*\(")
MODEL_CALL = re.compile(r"\b(?:runCrew|runLLMCouncil|runLLMStream|completeText)\s*\(")


def _code_keep_lines(src):
    """Like _code, but block comments keep their newlines so reported line numbers are the file's."""
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def _strip_imports(code):
    return re.sub(r"^[ \t]*import\b[\s\S]*?\bfrom\s*['\"][^'\"]+['\"][ \t]*;?",
                  lambda m: "\n" * m.group(0).count("\n"), code, flags=re.M)


def _prod_ts_files():
    for p in sorted(BACKEND_SRC.rglob("*.ts")):
        rel = p.relative_to(BACKEND_SRC)
        if "node_modules" in p.parts or "__tests__" in rel.parts or p.name.endswith((".test.ts", ".spec.ts", ".d.ts")):
            continue
        yield p, rel.as_posix()


def _line_of(code, pos):
    return code.count("\n", 0, pos) + 1


def _function_span(code, name):
    m = re.search(r"\bfunction\s+%s\b" % re.escape(name), code)
    if not m:
        return None
    end = code.find("\n}\n", m.end())  # closing brace in column 0
    return (m.start(), len(code) if end == -1 else end)


def _guard_helper_names():
    """Exports of hallucination_guard.ts that (transitively) call a Gate 1 entry point."""
    code = _code_keep_lines(GUARD_FILE.read_text(encoding="utf-8"))
    bodies = {}
    for m in re.finditer(r"\bexport\s+(?:async\s+)?function\s+(\w+)", code):
        end = code.find("\n}\n", m.end())
        bodies[m.group(1)] = code[m.end(): len(code) if end == -1 else end]
    gates = set(GATE_NAMES)
    changed = True
    while changed:
        changed = False
        for name, body in bodies.items():
            if name not in gates and any(re.search(r"\b%s\s*\(" % g, body) for g in gates):
                gates.add(name)
                changed = True
    # hallucinationGuard() is res.json() middleware: it never sees SSE writes, so naming it in a handler gates nothing.
    return gates - set(GATE_NAMES) - {"hallucinationGuard"}


def _researcher_chain_problems():
    problems = []
    coordinator_calls = 0
    for p, rel in _prod_ts_files():
        if rel == "crew/researcher.ts":
            continue  # the definition
        code = _strip_imports(_code_keep_lines(p.read_text(encoding="utf-8", errors="replace")))
        mentions = [m.start() for m in re.finditer(r"\brunResearcher\b", code)]
        reexport = re.search(r"\bexport\s*\*\s*(?:as\s+\w+\s*)?from\s*['\"][^'\"]*/researcher(?:\.[jt]s)?['\"]",
                             p.read_text(encoding="utf-8", errors="replace"))
        if rel != "crew/coordinator.ts":
            if mentions:
                problems.append("%s:%d uses runResearcher. Only crew/coordinator.ts (inside runCrew) may; this is a new "
                                "caller whose output is not covered by the /crew/chat Gate 1." % (rel, _line_of(code, mentions[0])))
            if reexport:
                problems.append("%s re-exports crew/researcher.ts, which makes runResearcher reachable from outside "
                                "coordinator.ts." % rel)
            continue
        span = _function_span(code, "runCrew")
        if span is None:
            problems.append("crew/coordinator.ts has no runCrew function; the test needs updating")
        for pos in mentions:
            where = "crew/coordinator.ts:%d" % _line_of(code, pos)
            if not re.match(r"runResearcher\s*\(", code[pos:]):
                problems.append("%s references runResearcher other than as a direct call (alias / callback)" % where)
                continue
            coordinator_calls += 1
            if span is None or not (span[0] <= pos < span[1]):
                problems.append("%s calls runResearcher outside runCrew, a path whose output no route gates" % where)
    if coordinator_calls == 0:
        problems.append("found no runResearcher( call in crew/coordinator.ts; the test needs updating")
    return problems


def _runcrew_caller_problems():
    problems = []
    callers = 0
    gate_names = sorted(set(GATE_NAMES) | _guard_helper_names())
    gate_re = re.compile(r"\b(?:%s)\s*\(" % "|".join(gate_names))
    for p, rel in _prod_ts_files():
        if rel.startswith("crew/"):
            continue
        code = _strip_imports(_code_keep_lines(p.read_text(encoding="utf-8", errors="replace")))
        refs = list(re.finditer(r"\brunCrew\b", code))
        if not refs:
            continue
        regs = [m.start() for m in ROUTE_REGISTRATION.finditer(code)]
        for m in refs:
            where = "%s:%d" % (rel, _line_of(code, m.start()))
            if not re.match(r"runCrew\s*\(", code[m.start():]):
                problems.append("%s references runCrew other than as a direct call (alias, re-export or callback); the "
                                "route-level Gate 1 cannot be checked" % where)
                continue
            callers += 1
            starts = [s for s in regs if s <= m.start()]
            if not starts:
                problems.append("%s: runCrew is called outside any route handler (new caller; its output reaches "
                                "runResearcher's model text with no Gate 1 route above it). Gate it like POST /crew/chat "
                                "and extend this test." % where)
                continue
            later = [s for s in regs if s > starts[-1]]
            handler_end = later[0] if later else len(code)
            after = code[m.start() + len("runCrew"): handler_end]
            gate = gate_re.search(after)
            if not gate:
                problems.append("%s: the route handler never runs Gate 1 (%s) after runCrew; everything it sends from "
                                "runCrew's output (reply, authority citation and relevance text, and runResearcher's "
                                "notes inside them) is ungated" % (where, "/".join(gate_names)))
                continue
            write = WRITE_TO_RES.search(after)
            if write and write.start() < gate.start():
                problems.append("%s: the handler writes to the response (%s) before Gate 1 runs (%s at +%d chars)"
                                % (where, write.group(0).strip(), gate.group(0).strip(), gate.start()))
            late_model = MODEL_CALL.search(after, gate.end())
            if late_model:
                problems.append("%s: model call %s after the Gate 1 call; its text is not covered by the gate"
                                % (where, late_model.group(0).strip()))
            sends_authorities = re.search(r"relevanceNote|\.authorities\b", after)
            before_write = after[: write.start()] if write else after[: gate.end()]
            if sends_authorities and not re.search(r"relevanceNote|\bauthorities\b", before_write):
                problems.append("%s: the handler sends authority citation/relevance text but the code between runCrew and "
                                "the first write never touches authorities/relevanceNote, so that text is not in the "
                                "gated draft. Gate it with the reply before anything is written." % where)
    if callers == 0:
        problems.append("found no runCrew( call outside crew/; the test needs updating (POST /crew/chat moved?)")
    return problems


class RunResearcherReachesOnlyAGate1Route(unittest.TestCase):
    def test_every_runresearcher_caller_chain_ends_in_a_gate1_route(self):
        with self.subTest(link="runResearcher is called only from runCrew in crew/coordinator.ts"):
            problems = _researcher_chain_problems()
            self.assertEqual(problems, [], "runResearcher's ungated model text can reach a caller no route gates "
                             "(finding 3 is covered only at the route):\n" + "\n".join(problems))
        with self.subTest(link="every runCrew caller outside crew/ is a route handler that gates before it writes"):
            problems = _runcrew_caller_problems()
            self.assertEqual(problems, [], "a runCrew caller can send ungated model text (runResearcher's notes "
                             "included):\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()

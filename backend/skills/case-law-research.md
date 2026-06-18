---
name: case-law-research
description: Systematic case law research using DingDuff legal research tools with AI-powered batch screening. Specializes in strategic opinion_search queries to find truly on point cases, efficiently screens multiple cases using case_screen, validates findings through actual opinion text retrieval, and builds comprehensive case law networks using citation and similarity analysis. Emphasizes quality over quantity with strict anti-hallucination safeguards.
---

# Case Law Research

## CRITICAL: Anti-Hallucination Protocol
**NEVER** discuss case content based solely on search snippets. **ALWAYS** retrieve actual opinion text via `opinion_extract` or `opinion_view` before discussing holdings. **CITE** cluster IDs and page references. Search snippets are for finding cases, not citing them.

## Phase 1: Strategic Search (Cast Wide Net)

Run 3-5 different search strategies to maximize coverage:

### A. Natural Language Semantic Search
```json
{"query": "when can police search vehicle without warrant during traffic stop", 
 "court_ids": "scotus", "filed_after": "2010-01-01"}
```

### B. Boolean/Proximity Search  
```json
{"query": "(automobile OR vehicle) AND warrant* AND \"probable cause\"~25",
 "court_types": "F", "precedential_status": "published"}
```

### C. High-Citation Authority (SCOTUS + Circuit)
```json
{"query": "[core legal issue]", "court_ids": "scotus",
 "order_by": "-citeCount", "page_size": 20}
```

### D. Jurisdiction-Specific
```json
{"query": "[issue]", "court_types": "S,SA", "states": "TX,CA,NY"}
```

### E. Field-Specific (via courtlistener_full_search)
```json
{"type": "o", "q": "court_id:scotus AND \"qualified immunity\"",
 "order_by": "-citeCount"}
```

**Court Types**: F=Circuit, FD=District, S=State Supreme, SA=State Appellate
**SCOTUS**: Use court_ids="scotus" (not a court_type)
**States**: Use 2-letter codes (TX, CA, NY)
**Boolean**: AND, OR, -, NOT, (), "exact phrase", term*, term~2 (fuzzy)

## Phase 2: Batch Screen (Filter to On-Point Cases)

Collect 15-30 cluster IDs from searches, then:

```json
{"cluster_ids": ["107252", "108713", ...],
 "relevance_criterion": "cases directly addressing [specific legal question with key doctrines and elements]"}
```

Submit with `submit_batch_screen`, poll with `retrieve_batch_screen`. Focus on cases scoring 8+.

## Phase 3: Extract Holdings (Get Actual Text)

For each highly relevant case:

```json
{"identifier": "347 U.S. 483",
 "relevance_criterion": "discussion of [specific doctrine/issue you need from this case]"}
```

Validate: ✓ Got full text ✓ Confirmed citation ✓ Found holdings ✓ Located quotes with pages

## Phase 4: Build Case Network

### Find Recent Applications
```json
{"identifier": "[citation or cluster_id]", "court_types": "F,FD", 
 "limit_results": 20, "order_by": "-dateFiled"}
```

### Find Related Cases (Include SCOTUS)
```json
{"identifier": "[cluster_id]", "court_ids": "scotus",
 "limit_results": 15, "order_by": "-citeCount"}
```

## Phase 5: Synthesize Findings

### Structure:
1. **Answer**: Direct response to research question
2. **Primary Authority**: 3-5 most on-point cases with:
   - *Case Name*, Citation (Court Year)
   - Holding: [specific holding]
   - Key Quote: "[exact quote]" Id. at [page].
   - Cluster ID: ###### 
3. **Supporting Authority**: Reinforcing cases
4. **Contrary Authority**: Conflicting holdings if any
5. **Trends**: Recent developments or circuit splits

## Quick Reference

### Search Optimization
- **Too few results?** Remove date filters, broaden terms, use fuzzy (~)
- **Too many results?** Add court_types, states, date ranges, citeCount filters
- **Circuit splits?** Search: "circuit split" OR "conflict among circuits"
- **Overruled?** Search: overruled OR abrogated OR "no longer good law"

### Common Patterns
```python
# Constitutional issue
1. opinion_search: court_ids="scotus", filed_after="2000-01-01"
2. opinion_search: court_types="F", filed_after="2015-01-01"  
3. Check circuit splits

# Statutory interpretation
1. opinion_search: "18 U.S.C. 1001" AND interpret*
2. opinion_search: "18 U.S.C. 1001" AND "legislative history"

# State law
1. opinion_search: court_types="S", states="TX"
2. opinion_search: court_types="SA", states="TX"
3. Federal interpretation: "Texas law" in federal courts
```

### Batch Screening Tips
- Optimal: 10-15 cases per batch
- Criterion: Be specific about legal elements needed
- Timeout: Reduce batch size or submit multiple batches

### Quality Checklist
☐ Multiple search strategies used
☐ 15-30 cases screened
☐ Actual opinion text retrieved for key cases  
☐ Citations verified with cluster IDs
☐ Quotes include page numbers
☐ Both binding and persuasive authority considered
☐ Recent developments checked via citing cases

## Remember
Quality > Quantity. Find 5-7 truly on-point cases rather than 50 tangential ones. Always show your work with cluster IDs for verification.

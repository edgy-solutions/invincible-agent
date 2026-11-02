# Ask the manual: ten questions about MRAD-ARR-0417

- **Date:** 2026-10-25
- **Lane:** `invincible-agent/lane/01`
- **Brief:** architect, overnight item 6. Ten questions a maintainer would ask about MRAD-ARR-0417, each answer citing a data module and a paragraph. Misses are recorded as defects; the retrieval ones get a fix, and the extraction ones go to `doc-tools/lane/7f`.
- **Seal:** `tests/test_ask_the_manual_mrad_arr_0417.py` (19 arms: 10 pass, 9 strict xfail).

## What was asked, and of what

- **The retrieval.** The only retrieval over this manual is the declared walk `s1000d_fault_walk` (`policy/overlays/openddil-lab/verbs/`). The seal runs the real declaration over the committed triples `tests/fixtures/s1000d_mrad/mrad.ttl`, with `fault_code=MRAD-ARR-0417`. It asks the walk, not a model.
- **The source of truth.** The six XML data modules in doc-tools `tests/fixtures/s1000d/mrad/`. Every expected answer string in the seal was grepped there, and all nine are present verbatim. So an extraction xfail is a real absence, never a typo.
- **A paragraph can only be cited by position.** The source XML carries no `id=` attribute. The seal's `ANCHOR` table records each answer's position (for example, 520A `preliminaryRqmts/reqSafety/warning[1]`). No arm checks those positions, because the XML is not in this repo.

## The ten

| # | A maintainer asks | Source answer (DM, position) | What the walk returns | Verdict |
| --- | --- | --- | --- | --- |
| 1 | What does the code mean? | 421A `faultCode/faultCodeText`: "Array module fault, section 3." | 421A + the text | **DM hit**; paragraph not citable |
| 2 | What do I check first, then what? | 421A `isolationProcStep[1]` "Re-run BIT…", then its yes-branch "Check module power LED", then "Reseat connector" | nothing | **extraction** miss |
| 3 | When do I replace, and with what? | 421A, third step's yes answer: "Replace array module." → 520A, 720A | 520A, 720A | **DM hit**; the *condition* is an **extraction** miss |
| 4 | In what order? | 520A `mainProcedure/proceduralStep[1..4]`, then 720A `[1..5]` | 520A before 720A, by `ORDER BY ?dmc` | right only by the codes' spelling; step text and order are **fixture lag** (doc-tools #131 emits them) |
| 5 | What tools? | 520A/720A `reqSupportEquip[1]`: "array module extraction tool", ODM-SE-0001 | nothing | **retrieval** miss (the part number is in the triples); the tool *name* is an **extraction** miss |
| 6 | Which spare, how many? | 720A `reqSpare[1]`; 941A item 0001: ODM-AM-0001 ×1 | 941A, ODM-AM-0001, 1 | **DM hit**; paragraph not citable |
| 7 | Gasket? Screws? | 941A items 0002 ODM-GS-0002 ×1, 0003 ODM-SC-0003 ×2; 720A steps 2–3 | only item 0001 | **retrieval** miss (both items are in the triples) |
| 8 | Any warning before I start? | 520A and 720A `reqSafety/warning[1]`: "Disconnect power before removal." | nothing | **extraction** miss. **SAFETY**: the walk sends a mechanic to 520A without its warning |
| 9 | Which illustration? | 941A figure ICN-ODMRAD-00001, "Array Module Assembly" | 941A, the ICN; hotspot null | **DM hit**; the figure title is a **retrieval** miss (it is in the triples) |
| 10 | How often is it inspected? | 320A para[1]: "Every 180 days, inspect the array face…" | 320A, "180 days" | **DM hit**; what the inspection involves is an **extraction** miss |

**Score.**
- **Data module:** 6 of 10 are answered (1, 3, 6, 9 and 10, plus 4 by accident).
- **Element below the module:** 4 of 10. The walk returns the fault code (Q1), the part number in 941A (Q6), the ICN (Q9) and the interval (Q10). `mrad.ttl` gives each its own node, and 941A's catalog items carry item numbers that the walk does not return.
- **Paragraph or step text a mechanic reads:** **0 of 10.**
  - The fixture carries no warning, step, isolation-test or paragraph text.
  - doc-tools' main has emitted procedural steps since #131, so for Q4 the zero is ours (fixture lag). For the rest it is extraction.
- **Not asked:** 040A's three descriptive `levelledPara`s are not extracted either. No question needed them, but "what is an array module" would.

## The defects

### Retrieval: the triples carry it, the walk does not return it

| Defect | Arm (strict xfail) | Control arm (passes) |
| --- | --- | --- |
| R1 tools: `mil:requiresTool` is on 520A and 720A, and no select reads it | `test_Q5_what_tools_do_i_need` | `test_Q5_the_triples_name_the_tool_for_both_procedures` |
| R2 the IPD returns one catalog item. The `ipd` select joins items through the procedure's `mil:hasPart`, so the gasket and screws, which no procedure `hasPart`s, never appear | `test_Q7_do_i_need_a_new_gasket_or_screws` | `test_Q7_the_triples_list_the_gasket_and_the_screws` |
| R3 the figure title: the `rdfs:label` on the figure is not selected | `test_Q9_the_walk_names_the_figure` | `test_Q9_the_triples_carry_the_figure_title` |

**Not fixed here, and why.** All three fixes widen `s1000d_fault_walk`'s `returns`. That changes `tests/fixtures/s1000d_mrad/walk-MRAD-ARR-0417.json`, which "changes only by ruling" and is sealed by `test_the_mrad_walk_contract_agrees_with_its_fixture.py`. The alternative, a sibling verb, needs its own capability grant and has no consumer. The brief says "fix the retrieval ones", but that does not on its face rule a contract change. So this records the fix and asks. If the ruling is yes, these are the selects (both `many`, which the loader requires to carry an `ORDER BY`), and the three xfail markers come off in the same commit:

```yaml
  tools:
    cardinality: many
    sparql: |
      PREFIX mil: <http://edgy-solutions.com/ontology/mil#>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT DISTINCT ?dmc ?part_number WHERE {
        ?fi a mil:FaultIsolationDataModule ;
            mil:hasFaultCode ?fc ;
            mil:refersToDataModule ?procDm .
        ?fc mil:hasFaultCodeValue ?fault_code .
        ?procDm a mil:ProcedureDataModule ;
                rdfs:label ?dmc ;
                mil:requiresTool ?tool .
        ?tool mil:hasPartNumber ?part_number .
      } ORDER BY ?dmc ?part_number
  ipd_items:
    cardinality: many
    integers: [quantity]
    sparql: |
      PREFIX mil: <http://edgy-solutions.com/ontology/mil#>
      PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
      SELECT DISTINCT ?dmc ?part_number ?quantity ?name ?figure_title WHERE {
        ?fi a mil:FaultIsolationDataModule ;
            mil:hasFaultCode ?fc ;
            mil:refersToDataModule ?procDm .
        ?fc mil:hasFaultCodeValue ?fault_code .
        ?procDm a mil:ProcedureDataModule ;
                mil:refersToDataModule ?ipdDm .
        ?ipdDm a mil:IllustratedPartsDataModule ;
               rdfs:label ?dmc ;
               mil:hasCatalogItem ?item .
        ?item mil:hasPartNumber ?part_number ;
              mil:hasQuantity ?quantity .
        OPTIONAL { ?item rdfs:label ?name . }
        OPTIONAL { ?ipdDm mil:hasFigure ?fig . ?fig rdfs:label ?figure_title . }
      } ORDER BY ?dmc ?part_number
```

**What was run.** Both bodies were run over `mrad.ttl` with rdflib, with `?fault_code` written inline as `"MRAD-ARR-0417"`:
- `tools` returns `(520A, ODM-SE-0001)` and `(720A, ODM-SE-0001)`.
- `ipd_items` returns all three 941A items: `ODM-AM-0001` ×1 "array module", `ODM-GS-0002` ×1 "connector gasket", and `ODM-SC-0003` ×2 "screw", each with the figure title "Array Module Assembly".
- The same run confirms R2's cause: the only procedure with a `mil:hasPart` is 720A, and its only part is ODM-AM-0001.

**What was not run.** Neither select has been run through `build_selects`/`shape_selects`. No `returns` entry has been drafted for them either, because that is the contract change the ruling decides.

### Extraction: in the source XML, not emitted by doc-tools. Packeted to `doc-tools/lane/7f`

These were checked against `doc_tools/parsers/s1000d_rdf.py` as it stands on doc-tools `main` (last parser change 2a1c9fa, #131), not only against our copy of its output.

| Defect | Arm (strict xfail) |
| --- | --- |
| E1 **SAFETY**: `reqSafety` warnings (520A, 720A) | `test_Q8_any_warning_before_i_start` |
| E3 isolation steps, tests and answers (421A) | `test_Q2_what_do_i_check_first`, `test_Q3_on_what_condition_do_i_replace` |
| E5 the support-equipment name. Only its part number is kept, as both `hasPartNumber` and `rdfs:label` | `test_Q5_what_the_tool_is_called` |
| E6 the planning paragraph text (320A). Only the interval value and unit are kept | `test_Q10_what_the_inspection_involves` |
| E7 040A `levelledPara` text | not sealed; no question needed it |

**The vector store does not rescue these.** doc-tools' Weaviate chunks for an XML module come from the same parser graph (`doc_tools/utils/xml_chunks.py`, `extract_chunks_from_graph`), and its `warning:N` branch reads `mil:hasWarning`. Only `mil_std_40051_rdf.py` and `iads_rdf.py` emit `mil:hasWarning`; `s1000d_rdf.py` does not. So an S1000D warning is missing from the chunks for the same reason it is missing from the triples. The fix has precedent in those two parsers, and it would feed both stores.

**#131's step text does not reach a chunk either.** This was read from the code, not run. `s1000d_rdf.py` puts `mil:hasStepText` on the step node. The chunker's step branch reads `mil:hasInstructionText` on the module root, and `s1000d_rdf.py` never emits that. So regenerating our fixture would fix the graph for Q4 and leave Weaviate without the steps. Packeted to 7f as the control to run: one `extract_chunks_from_graph` over 520A, counting `step:N` chunks.

**Upstream since this was written: doc-tools PR #170** (`7f/mrad-extraction-gaps`, head `6f0dedf8`). It is open and mergeable, and it is not on main. 7f reports it closes E1, E3, E5 and E6 in both the graph and the chunks:
- the warning is a root `mil:hasWarning` literal plus a citable node;
- new chunker walks for the isolation tree and the planning sections.

That is 7f's report, not a measurement here. The grep above found no procedural-step walk in #170. This note's arms measure our `mrad.ttl`, so they stay xfail until it is regenerated from merged output.

**There is no E2.** The first draft of this note had a generic "no node below the data module" arm. It was wrong in two ways:
- The fixture already has element nodes for the fault code, figure, catalog item and interval.
- doc-tools already mints positional step ids, so that arm would have gone XPASS on a regenerated fixture while the warning was still missing.

**Each text arm above carries the citation question for its own answer instead.** Once the text sits on its own node, the answer is citable. The source has no ids, so that node's identity has to be positional, as #131's `step-<scope>-<proc>-<step>` already is.

The extraction arms share one control: the same matcher finds a literal the triples do carry. It passes.

### Fixture lag: doc-tools emits it, our copy predates it. Ours

| Defect | Arm (strict xfail) |
| --- | --- |
| F1 procedural step text and order: an `rdf:List` of `mil:ProceduralStep` with `mil:hasStepText`, since #131 | `test_Q4_in_what_order` |

`mrad.ttl` was copied from doc-tools PR #63 at 4a6df088 (fixture README). Regenerating it from #131's output turns this arm XPASS, so its marker comes off then. That regeneration also moves `test_the_mrad_walk_contract_agrees_with_its_fixture.py`'s input. It is not done here: running doc-tools' parser needs doc-tools' own environment, and the walk contract is ruled.

## Measured

- The seal, run alone in its worktree's venv at `lane/01-ask-the-manual`: 10 passed, 9 xfailed. Strict xfail, `raises=AssertionError`, so a crash cannot pass as a recorded miss.
- **Mutant M1** (extraction): a triple carrying "Disconnect power before removal." appended to `mrad.ttl`. Exactly `test_Q8_any_warning_before_i_start` goes red (`XPASS(strict)`).
- **Mutant M2** (retrieval): the `ipd` select's `?fig mil:hasICN ?icn .` changed to `?fig rdfs:label ?icn .` (one site). `test_Q9_the_walk_names_the_figure` goes red (`XPASS(strict)`), and so does `test_Q9_which_illustration`, because the ICN is gone.
- Both restores were made by copy from an on-disk backup, and `cmp` found them identical. `git status` is clean on both paths afterwards.

## Not measured

- The live walk on the sandbox. This measured the declaration over the fixture, not the deployed verb.
- R1 and R2 were not mutated individually. Their arms share `_walk_says`, which M2 showed can fire.
- Whether the published triples on the sandbox match `mrad.ttl`.

# Retrieval baseline: 160-skill corpus

Date: 2026-09-11

This is the first frozen measurement of SkillDock's unchanged lexical/fuzzy scorer after the
`SearchProvider` boundary was introduced. It is deliberately a baseline, not a tuned result.

## Corpus and protocol

- Public sources: `NomaDamas/k-skill` (123 skills) and `mattpocock/skills` (37 skills)
- Source revisions: `944714350a6ed5138a0e81ef42b00771713766aa` and
  `3cca18b368ae95cdbdebbff572ccafa662551015`
- Active skills: 160
- HOT skills: 10
- Discovery-only skills: 150
- Queries: 40 (`evals/retrieval_queries.yaml`)
- Query routes: 10 HOT metadata-ranking cases and 30 non-HOT discovery cases
- Coverage: Korean-to-English descriptions, abstract intent, similar skills, and requests that
  do not contain the expected skill name

The HOT result is an offline proxy that ranks only the ten HOT tool descriptions. It does not
claim to measure a specific host model. The discovery result executes the same
`LexicalSearchProvider` path used by `find_skills`.

## Results

| Slice | Queries | Top-1 | Top-3 | Top-5 | MRR@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Overall | 40 | 37.50% | 47.50% | 57.50% | 0.4379 |
| Discovery-only | 30 | 36.67% | 50.00% | 53.33% | 0.4289 |
| HOT metadata proxy | 10 | 40.00% | 40.00% | 70.00% | 0.4650 |

| Category | Queries | Top-1 | Top-3 | Top-5 | MRR@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cross-language | 14 | 21.43% | 28.57% | 28.57% | 0.2381 |
| Abstract intent | 9 | 44.44% | 55.56% | 55.56% | 0.5000 |
| Similar skills | 10 | 50.00% | 70.00% | 70.00% | 0.5833 |
| Expected name absent | 7 | 42.86% | 42.86% | 100.00% | 0.5500 |

## What failed

The dominant failure is a language boundary. Korean prompts for English-only descriptions such
as `diagnosing-bugs`, `code-review`, `research`, `public-restroom-nearby`,
`parking-lot-search`, `building-register-search`, and `korean-heritage-search` frequently had
no meaningful token overlap. Small fuzzy scores then promoted unrelated Korean descriptions.

Ambiguous neighborhoods also exposed weaknesses:

- The four `daangn-*` skills compete strongly on shared boilerplate.
- KBL, KBO, K League, and LCK descriptions share sports/result terms.
- `handoff` and `claude-handoff` express the same family of intent.
- `hwp`, `rhwp-edit`, and `rhwp-advanced` require action-level distinctions that simple token
  overlap does not reliably preserve.

Two upstream records (`gongsijiga-search` and `housing-official-price`) currently expose only
`|` as their description. No retrieval backend can route those reliably without repaired source
metadata or an enrichment layer.

## Decisions supported by this baseline

1. Keep lexical search as the dependency-free default, but do not treat it as sufficient for a
   bilingual 100+ skill registry. A 53.33% discovery Top-5 rate and 28.57% cross-language Top-5
   rate are clear limitations.
2. Preserve the new provider seam and run a controlled optional hybrid/semantic experiment next.
   Compare it against cheaper bilingual alias/tag enrichment before selecting a default.
3. Keep the first live-host study at 5, 10, and 20 HOT tools. Ten HOT descriptions achieved only
   70% Top-5 in the offline proxy, so increasing the tool inventory without a host measurement is
   not justified yet.
4. Do not change the lexical weights from this dataset alone. Freeze this report, add a held-out
   set, and compare candidate providers on both to avoid tuning to the authored examples.
5. Host behavior remains a separate hypothesis: spontaneous `find_skills` invocation and actual
   HOT tool choice must be measured with `docs/compatibility.md` rather than inferred from this
   ranking benchmark.

## Reproduce

```console
skilldock install NomaDamas/k-skill --all
skilldock install mattpocock/skills --all
skilldock hot add korea-weather
skilldock hot add korean-transit-route
skilldock hot add delivery-tracking
skilldock hot add korean-spell-check
skilldock hot add korean-cinema-search
skilldock hot add diagnosing-bugs
skilldock hot add code-review
skilldock hot add tdd
skilldock hot add research
skilldock hot add to-spec
skilldock eval evals/retrieval_queries.yaml --min-skills 150 \
  --output retrieval-result.json
```

Those ten HOT commands reproduce this historical benchmark only. They are not a recommended
default and must not be run during normal installation without the user's exact selection.

The result JSON records the dataset digest, exact installed source revisions, corpus sizes,
revision mismatches against the frozen dataset, aggregate slices, and every query's Top-5 ranking.

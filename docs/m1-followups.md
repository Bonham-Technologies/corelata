# M1 follow-ups

## Divergences from Coglossa

- `text.py`: dropped `clean_guide`/`_clean` (translation-guide specific).
- `config.py`: RolesConfig has fixed roles gate/writer/conveyor/auditor/profiler and a model_for() helper; added StandardsConfig, PipelineConfig, IntegrationsConfig; dropped chunking/profiles/scorer/scoring; WorkerConfig defaults 2 / 900 s and no scorer_wait_s; _resolve() helper replaces the repeated model_copy blocks (backport).

- `llm/`: copied unchanged (rename only). `prompts/library.py`: copied unchanged. `schema/common.py`: LLMCallRecord and Usage lifted out of Coglossa's schema/report.py so the LLM layer does not depend on the report schema (backport candidate). `llm/registry.py`: import list re-sorted by ruff after the rename (`ConfigError, CorelataConfig`).

- `testing/fake_backend.py`, `fake_openai.py`, `pdf.py`: copied unchanged (rename only), except `FakeOpenAIServer.serve_forever` carries `# pragma: no cover` (blocking CLI-only path, not reachable from a test). `testing/synthetic.py`: rewritten for Corelata's roles (Task 10).

- `text.py`: added `key_terms()` (shared by the gate's unit ranking and the synthetic responder).

- `ingest/`: base, txt, markdown, docx, html, pdf copied unchanged; epub dropped; registry.py gains JsonIngestor/CsvIngestor and says "no usable text" instead of "no translatable text". tabular.py is new. Copied tests: `test_html.py`/`test_registry.py` match "no usable text"; `test_pdf.py` extension list drops ".epub".

## Spec deviations

- §5.3 says the adapter validates against the vendored JSON Schema; M1 validates with a pydantic subset of it (no jsonschema dependency) and refuses unknown schema_version. The vendored file is kept and a test checks the subset's field names against it.
- §8.4 invariant 1 ("every claim in a delivered report has evidence") holds for status=clean by engine enforcement, not by trusting the model: the engine overrides icd203.tc.8 (and icd206.src.2 for key-judgment claims) to FAIL whenever a claim is unsourced. A findings_open report keeps unsourced claims so the analyst sees what failed; they are listed in metadata.open_findings via icd203.tc.8.
- §4.4 lets the conveyor add claims that cite existing units; M1's validator keeps the claim set fixed (reword only). Relax in M2 if real models need it.
- §13 says "disable wins over override"; M1's loader treats a profile that both disables and overrides the same rule id as an error (controller Ruling 2).
- §6.6 pack_hash: M1 stores the first 16 hex chars of the SHA-256, not the full digest (same convention as config_hash).

## Should fix soon


## Spec issues to raise

- §7.2 loop wording is inconsistent ("iteration < max_iterations" vs "iteration == max_iterations → rendering"); M1 implements max_iterations = number of revisions (default 2 → up to three audits).
- §7.5 oversize ladder: halving the digest threshold cannot shrink auditor or conveyor requests.

## Later

- doctor command (M3, needs the database) — **closed in M3** (`corelata doctor`)
- profile extract (M6) — **closed in M6** (`corelata profile extract`)
- shared foundation package extraction (after both products deploy) — CRL-3
- pack-level prompts/ overrides (§6.1)
- `corelata pack diff` (§6.8) — **closed in M7** (BORG-36)

## Closed in M2

- Digest chunking (`pipeline.digest_chunk_tokens`) and per-unit oversize fail-fast.
- `pack_hash` is key-sorted and ignores excluded fields.
- §7.4 writer context amended: all non-digested units within `pipeline.writer_unit_budget_tokens`.
- HTML and DOCX renders; `corelata report` and `corelata trace`.

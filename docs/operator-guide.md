# Corelata operator guide

## 1. What Corelata is

Corelata turns source documents and an analyst's value statement (what the report is for and why it
matters) into an intelligence assessment shaped by ICD 203: key judgments with likelihood and
confidence language, sourcing, alternatives and gaps. Every claim is traced back to the passages of
the sources that support it, and the whole run (each model call, each rule check, each revision) is
kept so a reviewer can see how the report came to be. Reports export as DOCX, HTML, Markdown and a
JSON trace.

It runs unattended. The web app and the command line queue a run in a Postgres job queue; a worker
picks it up, writes, checks and revises the report, and stores the result. The whole stack runs on
one Linux host under Docker and never needs the internet: the only servers it talks to are your own
OpenAI-compatible model servers.

### The bundle

```
corelata-<version>/
  images/                              the Docker images
  config/corelata.example.yaml         the template for your configuration
  config/corelata.demo.yaml            the configuration the demo uses
  config/packs.example/icd203-base/    the base standards pack (ICD 203 and ICD 206 rules)
  examples/                            a sample source for the demo (varna-port.txt)
  compose.yaml                         the services: database, migrate, worker, API with the web app
  compose.demo.yaml                    adds a synthetic model server, to try the stack
  install.sh  backup.sh  restore.sh    install or upgrade, back up, restore
  operator-guide.md                    this guide
  sbom/                                software bills of materials (CycloneDX)
  manifest.json                        version, commit, platform, image ids, Postgres digest, packs
  VERSION                              the bundle's version
  SHA256SUMS                           checksums of every file in the bundle
```

## 2. Requirements

- **Host:** Linux x86_64 with Docker Engine 24 or newer and the Compose plugin 2.24 or newer.
  Check with `docker compose version`.
- **Software on the host:** bash, coreutils and tar.
- **Disk:** about 2 GB for the images, plus room for the bundle while you unpack it, your sources,
  the exports and your backups.
- **A model server** reachable from the host: vLLM, Ollama, TGI, a llama.cpp server or LM Studio,
  anything that exposes an OpenAI-compatible `/v1` API. It can run on the same host or elsewhere on
  your network.
- **Network:** no internet access is needed, at install or at run time.

## 3. Install

Each version is published as a GitHub release of the `Bonham-Technologies/corelata` repository
(`corelata-<version>-linux-amd64.tar`, its `.sha256`, the manifest, and a `SHA256SUMS` that
covers the tar and the manifest); your vendor hands you these files, since the air-gapped host
cannot fetch them.

1. Check the copy, then unpack it:

   ```sh
   sha256sum -c corelata-<version>-linux-amd64.tar.sha256
   tar -xf corelata-<version>-linux-amd64.tar
   cd corelata-<version>
   ```

2. Run the installer:

   ```sh
   ./install.sh
   ```

   It checks every file against `SHA256SUMS`, checks for Docker Compose 2.24 or newer, loads the
   two images into Docker, and creates three things if they do not exist: `config/corelata.yaml`
   (a copy of the example), `config/packs/` (a copy of `config/packs.example/`: your standards
   packs) and `.env` (a random database password, readable only by you). It never overwrites them,
   so it is safe to run again; they are not in `SHA256SUMS`, so your edits never fail the check.
   Keep `.env`: the database was created with that password.

   It also makes `config/` world-readable (`chmod -R a+rX config`). The containers run as uid
   10001 and read `config/` through a read-only mount, and a strict umask (027, 077) would hide
   the files from them. Nothing in `config/` is secret: model-server keys go in `.env`.

3. Edit `config/corelata.yaml`. Three parts matter to start with (section 5 explains them):
   `backends` (your model servers), `models` (the model ids on them) and `roles` (which model does
   which job). Find a model id with `curl http://<server>:<port>/v1/models`.

4. Start it and check it:

   ```sh
   docker compose up -d --wait
   docker compose exec api corelata doctor
   ```

   `doctor` checks the configuration, the database, the files volume, the standards pack and each
   model server. For a server it reports how many models it serves and whether each model you
   configured is among them (a missing one's fix suggests up to five ids with the same prefix);
   then it sends each model a small test completion and, for a model set to `json_schema` or
   `json_object`, asks for a real gate verdict with the same schema and request builder a run
   uses, so a server that would reject a run's schema fails here, with the server's own error.
   The model you configured as auditor gets one more line, `model <key> auditor schema`: the
   auditor's schema has one required property per rule of your pack, the largest a run sends,
   and some servers limit schema size. Every check must pass or warn; a failing check says what
   to fix. A model whose first reply to a probe is not the requested JSON gets one repair turn,
   as every call in a run does: if the repaired reply works, the line is a warning
   ("json_object output works after one repair turn") and the model can be used, at the price of
   a second request on some calls.
   Add `--no-probe` to skip the test completions.

5. Open `http://<host>:8080` in a browser. To publish the port on this host's loopback address
   only (behind a reverse proxy, or reached through an SSH tunnel), add
   `CORELATA_HTTP_BIND=127.0.0.1` to `.env`; `CORELATA_HTTP_PORT` changes the port. Apply either
   as in "Applying changes" (section 5).

## 4. Try it first (demo)

The demo needs no model server. It uses a synthetic model that answers every request with a
placeholder, so the reports are structurally complete but say nothing true. It is for seeing the
stack work.

Compose needs the database password, and the demo needs the images. Run `./install.sh` first (it
loads the images and creates `.env` with the password, which Compose reads from the current
directory). To try the demo without installing, load the images yourself
(`docker load -i images/app.tar` and `docker load -i images/postgres.tar`; `docker load` reads one archive per command) and `export CORELATA_DB_PASSWORD=demo`
before the commands below. (`make demo` is a developer shortcut in the source repository, not in
the bundle.)

```sh
docker compose -f compose.yaml -f compose.demo.yaml up -d --wait
```

The overlay names its own project, `corelata-demo`, so the demo's data never mixes with a real
installation's. Run a report from the shell, then open `http://<host>:8080` and find the project
`demo`:

```sh
docker compose -f compose.yaml -f compose.demo.yaml exec worker corelata run \
  /opt/corelata/examples/varna-port.txt --project demo \
  --statement "Varna port capacity expansion matters to shippers"
```

The command queues the run and returns; the worker does the rest. Follow it with
`corelata status <run-id>` (the id is in the command's output) run the same way, or watch it in the
web app.

Remove the demo, its data included:

```sh
docker compose -f compose.yaml -f compose.demo.yaml down -v
```

**Rehearsing an installation with the demo model.** To try backups, an upgrade and a restore
without a model server, make the overlay part of this directory's Compose setup instead of
passing `-f` each time: after `./install.sh`, add one line to `.env`:

```
COMPOSE_FILE=compose.yaml:compose.demo.yaml
```

Every plain `docker compose` command in this directory then acts on the demo stack, and so do
`backup.sh` and `restore.sh`, which run them: sections 7 to 10 apply as written, and section 10
carries the line over when it copies `.env`. In section 12 the plain `docker compose down -v`
removes only the demo stack (the `corelata-demo` project), so skip its `-f` form. Two differences: the stack reads
`config/corelata.demo.yaml` (the overlay sets it), not `config/corelata.yaml`, so editing
`config/corelata.yaml` changes nothing for this stack, and you should leave the demo file as
shipped: it is listed in the bundle's `SHA256SUMS`, and running `./install.sh` again in this
directory refuses an edited copy as a damaged bundle; and the Compose project is `corelata-demo`,
so the volumes are `corelata-demo_pgdata` and `corelata-demo_files`, not the names section 7
gives (see "Where the data is"). To move to your model servers, run `docker compose down -v` (the demo's data goes with it), remove
the line, edit `config/corelata.yaml` and start as in section 3.

Stop the demo before you start the real installation: both publish port 8080 (or set
`CORELATA_HTTP_PORT` for one of them).

## 5. Configuration

Everything is in `config/corelata.yaml`. Unknown keys are an error, so a typo is caught at start.
Relative paths are relative to the file. The database is set by the containers
(`CORELATA_DATABASE_URL`); do not add a `database` section.

### Model servers

```yaml
backends:
  local:
    base_url: http://host.docker.internal:8000/v1
    api_key_env: CORELATA_LOCAL_KEY
    max_concurrency: 4
    timeout_s: 120
```

- `base_url` ends in `/v1`, with no query string (`?…`) and no fragment (`#…`): Corelata adds
  `/chat/completions` and `/models` to it, which would land inside a query, so such a URL is a
  configuration error, as is one without `http://` or `https://` and a host, or one that
  already ends in `/chat/completions` or `/models`. From inside a container, a server running on
  the host itself is at `host.docker.internal` (the compose file maps it); a server elsewhere is
  at its own address.
- `api_key_env` names an environment variable that holds the key. Add the variable to `.env`
  (`CORELATA_LOCAL_KEY=...`), not to the YAML. A name with no matching variable is a configuration
  error. Leave it out for a server that needs no key.
- `max_concurrency` (default 4) caps simultaneous requests to that server; `timeout_s` (default
  120) is the time allowed for one request. Raise `timeout_s` for a slow server or a long report.

### Models and roles

```yaml
models:
  strong:
    backend: local
    name: Qwen/Qwen3-32B
    context_window: 32768
    structured_output: json_schema
    max_output_tokens: 8192
    temperature: 0.2
roles:
  gate:     { model: strong }
  writer:   { model: strong }
  conveyor: { model: strong }
  auditor:  { model: strong }
```

- The key under `models` (`strong`) is what roles refer to. `name` is the model id exactly as the
  server lists it; it defaults to the key.
- `context_window` is the model's window in tokens (at least 2048); Corelata splits sources to fit.
- `structured_output` is `json_schema` (the server enforces the schema: vLLM, Ollama, TGI),
  `json_object` (the server guarantees JSON, the schema is described in the prompt) or `none`
  (plain text; Corelata extracts the JSON). Use the strongest the server supports.
  With `json_schema` the schemas are sent in the strict form every OpenAI-compatible server
  accepts (all properties required, no extra keys). OpenAI-family servers cap enum size at 1,000
  values and 15,000 characters. The audit schema caps its unit-id enum at 200 values
  (`ENUM_LIMIT`), under the provider cap of 1,000.
  The writer and conveyor send a per-call schema whose `evidence` items are the run's unit ids
  but parse the reply as the canonical report, so a `json_schema` server cannot generate a bad
  ref and every other server gets the ref error in the same repair message as the other
  validator errors.
- With `json_schema` the server also enforces the auditor's shape: every rule id exactly once,
  only the verdicts the rule allows, only unit ids the draft cites. With `json_object` or `none`
  the same schema is in the prompt and Corelata checks the reply itself, so a small model needs
  its repair turn more often. If you override prompts (`prompts_dir`), an `auditor` override
  must return `findings` as an object keyed by rule id, as the built-in `auditor/v6.j2` does; an
  override that still returns a list fails every audit.
- `max_output_tokens` is unset by default (the server decides); `temperature` defaults to 0.2.
- `request_extra` (CRL-140) is a mapping of keys added to every request body for that model,
  exactly as written: a server's own options, which Corelata does not know. The common one turns
  a reasoning model's thinking off, for Qwen3 on vLLM or SGLang
  `chat_template_kwargs: { enable_thinking: false }`; other servers name theirs differently
  (`reasoning_effort: low` for gpt-oss and OpenAI-family servers). The keys Corelata sets itself
  are refused when the config loads, each with the setting to use instead: `model` (`name`),
  `messages`, `response_format` (`structured_output`), `temperature`, `max_tokens`
  (`max_output_tokens`) and `stream` (Corelata reads one whole reply), and with them `n`,
  `tools`, `tool_choice`, `functions` and `function_call`, since Corelata reads the text of one
  choice only. Values must be plain JSON (strings, numbers, booleans, lists and mappings; quote
  a date). `corelata doctor` sends them too. They shape the output, so they are part of the
  config hash; never put a key or other secret here (use `api_key_env`), since the config is
  stored with every run.
- Reasoning models (Qwen3, DeepSeek-R1, gpt-oss) think before they answer. A server with a
  reasoning parser returns the thinking beside the answer (`reasoning`, or `reasoning_content`
  on older vLLM and DeepSeek's API); one without returns it in the answer as a leading
  `<think>...</think>` block, which Corelata skips before reading the JSON, so it costs no
  repair turn. `store_reasoning: true` keeps the thinking with each call in the run's
  `trace.json` (`llm_calls[].reasoning`), at most `reasoning_max_chars` characters of it
  (default 20000); it is off by default and needs `audit.store_llm_io` on as well. Neither
  setting changes the config hash. Reasoning spends output tokens: leave `max_output_tokens`
  unset or generous. A structured-output mode may stop a server from reasoning at all,
  depending on its version and flags: `corelata doctor` says, on each model's line,
  "reasoning: present under json_schema" or "absent" (the mode named is the model's own),
  read from the reply to its GateVerdict probe (for a `none` model, its test completion); a
  line that fails, or a `none` model whose test completion was cut at its 50 tokens (as a
  reasoning model's often is), says nothing about reasoning.
- The four roles: `gate` decides whether the sources can support the value statement at all,
  `writer` drafts the assessment, `conveyor` revises it to fix what the audit found, and `auditor`
  checks the draft against the standards. Use a model from a different family for the `auditor`
  when you have one: a model that checks its own work shares its blind spots. An optional fifth,
  `structurer`, maps a finished report onto the report schema for a check ("Checking an existing
  report", section 7); without it the writer's model does that.

### Standards packs

A pack is the standard a report is held to. `config/packs/` is yours; `install.sh` puts the base
pack there once and never touches it again.

```
config/packs/icd203-base/
  pack.yaml             name, version, description
  rules/<id>.yaml       one rule per file, e.g. icd203.as.1.yaml
  template.yaml         section order, key-judgment limits, word limit
  lexicon.yaml          likelihood terms, confidence definitions, source descriptors, markings,
                        source access terms
  profiles/<team>.yaml  an overlay for one team (optional)
```

- A **rule** has an `id` (lowercase, dot-separated), `title`, `text`, `source`, a `severity`
  (`blocking`, `major` or `minor`), a `checkability` (`verifiable`: the auditor can check it
  against the text; or `advisory`: a judgment call), `applies_to` (which of `writer`, `conveyor`,
  `auditor` see it), `evidence_required` (what the auditor should look for) and `route_to`
  (`writer` or `conveyor`: who fixes a finding). An optional `with_prior_reports` block
  (`checkability`, `evidence_required`) marks a rule that judges a report against the project's
  earlier accepted reports (`icd203.tc.7` in the base pack): a run that read some uses the
  block's two fields instead, a run in a project with none records the rule `not_applicable`
  (initial coverage), and a run that reads none (`pipeline.prior_judgments.max_reports: 0`) uses
  the rule as written. A profile `override` of `checkability` or `evidence_required` changes
  the rule as written only; while the block is there, a run that read earlier reports uses the
  block.
- A **profile** adapts the pack for a team without editing the pack: `extends` names the pack,
  `rules` can `add`, `disable` or `override` (severity, checkability, route_to, text,
  evidence_required) rules by id, `template` tightens the template, `tone` is guidance for the
  writer, `lexicon` adds handling markings and source descriptors, and `format.docx_reference`
  names a Word file whose styles the DOCX export uses. Put that file next to the profile
  (`profiles/team-east.docx`) and name it relative to the pack directory
  (`docx_reference: profiles/team-east.docx`); a file that is not a readable .docx is refused when
  the pack loads.
- **Sourcing (ICD 206).** A lexicon with a `source_access` list (the base pack's is `direct`,
  `indirect`, `unknown`) has every source entry carry its date of information, its originator
  and its access, one of those terms; a template whose `section_order` lists `source_summary`
  has the report carry a source summary statement (the source base's strengths and weaknesses,
  the sources the key judgments depend on most, which sources corroborate and which conflict).
  Every render numbers the sources and cites them by superscript number. A profile turns either
  off with `template: {source_details: false}` or `template: {source_summary: false}`. The
  writer reads a date and an author or publisher from an HTML page's `<meta>` elements and a
  Word file's properties as hints, and a Coglossa export's note names its reliability tier (the
  lowest tier among its scored spans), which the review screen's Sources tab shows too.
- **Uncertainty wording (ICD 203).** A lexicon with `likelihood_alternates`,
  `unlisted_probability_words` or `confidence_phrases` has the engine check every key judgment
  and judgment claim: a confidence phrase in the same sentence as a likelihood ("we assess with
  high confidence that it is likely"), a word from another row of the ICD 203 table or none
  ("probably", "perhaps"), or a claim whose text does not use its own likelihood term fails
  `icd203.tc.2` as an engine finding (`engine check: c3 uses probability wording outside the
  lexicon ('probable')`), and the writer revises. Matching ignores case and takes whole words, so
  "unlikely" is not "likely"; a term also matches its adverb ("almost certainly"). The base
  pack's lists come from the ICD 203 table; edit them in `lexicon.yaml`. A profile that mixes rows
  on purpose (ICD 203 then asks for a disclaimer) relaxes the check by disabling `icd203.tc.2` or
  overriding its severity to `minor`. The model is not sent these lists.
- `draft: true` marks a profile that is still under review. A run cannot use a draft profile;
  remove the flag when the team has approved it.
- `standards.default_pack` (default `icd203-base`) and `standards.default_profile` choose what a
  run uses when the analyst picks nothing.

A pack edit needs no restart. The API re-reads the pack list when a file under `config/packs/`
changes and checks for changes at most once a second, so the API sees an edit within a second; a
project page that is already open keeps the list it loaded, and opening it again after a
minute, or reloading, shows the edit; the resolved pack is read from disk on each request. A run
loads and snapshots its pack when it is started, so an edit applies to the next run; runs already
started keep the pack they began with. A pack directory may be a symbolic link to a directory
elsewhere, and edits inside it are seen the same way; the link's target must be inside what is
mounted into the containers (a link to a host path outside `config/` is broken inside them). Every
file under the pack directories is checked, through links too, so keep only pack files there.
Check your edits
first:

```sh
docker compose exec api corelata pack validate /etc/corelata/packs/icd203-base
docker compose exec api corelata pack show icd203-base --profile team-east \
  --packs-dir /etc/corelata/packs
```

`validate` lists errors and warnings (a draft profile is a warning); `show` prints the resolved
pack, which is what a run snapshots into its trace.

**Drafting a profile from a team's reports.** Put three or more of the team's finished reports
(`.docx`, `.md`, `.txt`, `.pdf`, `.html`) in a directory inside the files volume, then:

```sh
docker compose cp team-east-reports api:/data/files/team-east-reports
docker compose exec api corelata profile extract \
  --from /data/files/team-east-reports \
  --out /data/files/team-east.yaml
docker compose cp api:/data/files/team-east.yaml config/packs/icd203-base/profiles/team-east.draft.yaml
```

The command needs `roles.profiler` in `config/corelata.yaml` (point it at your strongest model)
and writes a profile with `draft: true` whose header lists the model's observations. It writes to
the files volume because `config/` is mounted read-only inside the containers; the last line
copies the draft into the pack on the host. Rename it to `team-east.yaml` once reviewed; never
copy over a profile the team has approved. Review every line, then remove the `draft` flag.
`--extends` picks the pack (default `standards.default_pack`), `--name` the profile name
(default: the `--out` file's name without its extension), `--force` overwrites an existing file;
without it an existing profile is never touched. The command warns if the name is already a
profile of the pack, since copying the draft into `profiles/` under that name would replace the
team's approved one.

### Pipeline

```yaml
pipeline:
  max_iterations: 2
  digest_threshold_tokens: 6000
  digest_chunk_tokens: 4000
  writer_unit_budget_tokens: 16000
  gate_unit_budget_tokens: 12000
  evidence_quotes: required
  quote_match_threshold: 1.0
  prior_judgments: { max_reports: 3, budget_tokens: 2000 }
```

- `max_iterations` (default 2, up to 10) bounds the audit loop: after the first draft the auditor
  checks it and the conveyor revises, up to this many times. The report is delivered either way;
  findings that remain open are marked as such. Revision rounds, under More options on the
  project page, starts at this value, and the analyst can change it for one run.
- Sources longer than `digest_threshold_tokens` are condensed into digests of at most
  `digest_chunk_tokens` per request before the writer sees them; `writer_unit_budget_tokens` and
  `gate_unit_budget_tokens` limit how much full text the writer and the gate are given.
- Raise the budgets when your models have a large context window and reports lose detail; lower
  them for a small window or a slow server. Keep them well inside `context_window`.
- `evidence_quotes` (`required`, `optional` or `off`) decides whether each claim quotes the
  words of its sources. With `required` (`engine/corelata.example.yaml` sets it; the stack's
  `config/corelata.example.yaml` does not yet, so add the line to opt in), the writer copies a
  passage of every unit a claim cites into the claim's `quotes` (units of a digested source
  excepted), and the engine checks each quote against the unit: a quote that is not there, or a
  cited unit left unquoted, fails `icd203.tc.8` (and `icd206.src.2` when a key judgment rests on
  the claim) as an engine finding such as `engine check: quote not found in src2/u14 (c3)`, and
  the writer revises as it does for an unsourced claim. The Claims tab then marks the quoted
  words inside each passage, the auditor reads each quote beside its passage, and the renders
  add a "Cited passages" appendix. `optional` checks the quotes a model gives without asking for
  one per unit; `off` is Corelata as it was before quotes, and is what a config without the key
  gets, so an upgraded install changes nothing until you add the line. Choose `optional` or
  `off` for a weak model that keeps paraphrasing inside its quotes: watch for runs that spend
  every revision on `quote not found` findings. The built-in `writer` (v2), `conveyor` (v2) and
  `auditor` (v3) prompts ask for, keep and read the quotes; with `off` they say what the
  previous versions said. A `prompts_dir` override of the writer must ask for `quotes` itself,
  or under `required` every claim fails with `no quote from …`. `corelata bench --scenarios real` includes a
  faithful-quote scenario (`quoted-customs-figures`) and a fabricated-quote one
  (`borrowed-quotation`) to try a model on.
- `quote_match_threshold` (0.5 to 1.0, default 1.0) is the share of a quote's words that must
  match a run of the unit's words in order. Case, whitespace, quote marks and other punctuation
  never count, so 1.0 is exact word for word. Lower it (0.9) only when sources are noisy, such as
  OCR'd scans: a lower threshold also lets a changed figure through.
- `prior_judgments` is the project's memory (ICD 203 asks a product to say how its judgments
  stand against previously published analysis, `icd203.tc.7`). It is off until you turn it on:
  a config without the key gets `max_reports: 0`, so an upgraded install changes nothing until
  you add the line (`engine/corelata.example.yaml` sets `max_reports: 3`; the stack's
  `config/corelata.example.yaml` does not yet). Once on, before drafting, a queued run
  reads the key judgments (text and confidence), title and acceptance date of the project's
  `max_reports` (up to 20) most recently accepted reports: completed runs whose review
  decision is **Accept**. Returned, gate-rejected and unreviewed runs, and other projects' runs,
  are never read. The writer then fills a "Changes from previous analysis" section (after the key
  judgments in every render): for each earlier judgment on its topic, whether the report is
  consistent with it or changes it, and why. The auditor reads the same judgments, and in the
  built-in pack `icd203.tc.7` becomes a checked rule (pass or fail, minor) through its
  `with_prior_reports` block; in a project with no accepted report it is `not_applicable`
  ("initial coverage"), recorded by the engine. `budget_tokens` (default 2000, at least 100)
  caps what those judgments take of the writer's input: the newest reports are kept while they
  fit, and the oldest are left out first. The budget comes on top of
  `writer_unit_budget_tokens`, and the auditor receives the same judgments, so on a server with a
  small context window lower one of them when you turn this on. Earlier judgments are copied
  into the new run whatever handling marking their report carried: every report in a project
  should share one marking, or keep project memory off for that deployment. The trace (`prior_reports`) and the review screen's
  Process tab list the reports read and those left out. `max_reports: 0` (or no
  `prior_judgments` key) reads nothing: the
  run, its requests and its trace are what Corelata made before project memory, with
  `icd203.tc.7` attested as before. `corelata run` without `--project` and `corelata bench` have
  no project, so they never read earlier reports. A pack copied before this release (the
  install never overwrites `config/packs/`) has no `with_prior_reports` block: the writer still
  reads the earlier judgments, and `icd203.tc.7` stays advisory; merge the block from
  `config/packs.example/icd203-base/rules/icd203.tc.7.yaml` to check it. The built-in `writer`
  (v3 and later) and `auditor` (v4 and later) prompts ask for and read them, and say what the
  versions before them said when a run read none; a `prompts_dir` override of either should mention
  `INPUT_JSON.prior_reports` and `changes_from_previous` itself.

### Uploads and the API

```yaml
api: { max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64 }
auth: { mode: none }
```

`max_upload_mb` is the size limit for one uploaded source (a reverse proxy in front must allow at
least as much, section 6). The API enforces it on the request body as well as on the file: a
request that announces more than the limit plus 64 KB for the form's own framing in its
`Content-Length` gets 413 before any of its body is read, and a request sent without a length
(chunked), or with one that understates the body, is counted as it is read and gets the same 413
once it passes that size. Nothing past the limit is written to the API's temp disk, and the
partly written temp file is removed. A proxy's body limit is still worth keeping: it refuses an
oversized upload before it reaches the API at all.
`auth` is explained in section 6.

The worker tells the API about every change to a run through the database (Postgres
`LISTEN`/`NOTIFY`), so the writing page updates as soon as a stage is recorded; the API also reads
each watched run every `progress_poll_s` × 10 seconds (at most 30, never less than `progress_poll_s`) in case a message was lost.
`progress_poll_s` (default 1.0) is how often it reads instead while its listening connection is
down, after a database restart for example; it reconnects after 1, 2, 4, 8, 16 and then every 30
seconds, and `docker compose logs api` shows `progress listener lost the database` and
`progress listener connected`. A connection pooler in transaction mode (PgBouncer) between the
API and Postgres passes no notifications: connect the API to Postgres directly, or progress shows
only at the heartbeat. The listening connection uses TCP keepalives (60 s idle, 10 s interval, 3
probes), so a firewall that drops idle sessions is detected within about 90 s. A site-set
`idle_session_timeout` ends the idle LISTEN session on its schedule; the API logs the WARNING and
INFO reconnect lines each time while streams stay correct.

`render_cache_mb` (default 64) is how much memory the API keeps for reports re-rendered with
claim ids, which the review screen shows; the oldest are dropped first, a report larger than the
whole budget is rendered on every request instead, and 0 turns the cache off.
`worker.concurrency` (default 2) is how many jobs one worker executes at once, runs and
discoveries (**Suggest value**) together; a discovery takes the next free slot ahead of runs
that are waiting, but it does not stop a run already in progress;
`worker.stalled_after_s` (default 900) is how long a worker may be silent before its jobs are
started over, and after which a cancel ends its run at once (section 7);
`worker.job_retention_days` (default 30) is how long failed and cancelled jobs are kept.
A discovery has two limits, both at least 60 s, and each holds whether or not a worker is
running. `worker.discovery_start_deadline_s` (default 3600) is how long a discovery may wait for
the worker to start it: one not started by then is failed with "Discovery did not start within
60 minutes and was stopped: the worker was stopped or busy with runs. Start a new discovery.".
`worker.discovery_deadline_s` (default 600) is how long a discovery may work once the worker has
started it: one not finished by then is failed with "Discovery did not finish within 10 minutes
and was stopped. Start a new discovery.". The time each message names is its setting. While a
discovery waits, the project page says "Waiting for Corelata to start looking…"; once
it runs, "Looking for value in the selected sources…"; and it shows either failure without a
reload. `GET /api/discoveries/<id>` reports the limit that applies as `deadline_at`: its
creation plus `worker.discovery_start_deadline_s` while it waits, and the worker's first claim
plus `worker.discovery_deadline_s` once it has started. Raise `worker.discovery_deadline_s` for a slow model server, and
`worker.concurrency` or `worker.discovery_start_deadline_s` when long runs keep the worker busy.

### Scanned PDFs

```yaml
ingest: { ocr: off, ocr_languages: [eng] }   # off (the default) or auto
```

A PDF page that shows a picture and has no text layer (a scan, a photographed or faxed page) has
no text to read. With `ocr: off` such an upload is refused with "needs OCR (needs_ocr)". With
`ocr: auto`, Corelata reads those pages with Tesseract, an offline text recognition program in the
app image: each page is rendered at 300 dpi and read in the languages `ocr_languages` lists, in
Tesseract's codes (`eng`, `fra`, `deu`, `rus`, `ara`, `chi_sim`, ...). Pages that have a text layer
are read as before; nothing leaves the machine. The demo configuration sets `ocr: auto`.

Text recovered this way may contain recognition errors, so it is marked. Each passage read by
OCR carries `ocr: true` and Tesseract's mean word confidence (0 to 100) in the trace; the writer
and the auditor are told which passages came from a scan (prompts `writer/v4` and `auditor/v5`), so
the source's reliability note and the quality-of-sources rule (`icd203.tc.1`) can say so; the report's Sources section, the Sources tab
of the review screen and `corelata trace` say "text recovered by OCR (N pages)".

The pages are read while the upload is answered, one page per CPU at a time across all uploads:
about three seconds per page per CPU core, and up to six for a page of dense small print, so a
50-page scan is answered in one to two minutes on four cores. The API sets
no time limit on an upload, but a reverse proxy may: raise its read timeout (nginx:
`proxy_read_timeout 5m;` in `location /`) if large scans fail with 504. A page with some text
and a picture (a typed header over a scanned body) has a text layer and is not read by OCR.

`corelata doctor` prints an `ocr` line: whether Tesseract is installed, its version and the
languages it has. It warns when `ocr: auto` is set and Tesseract or one of `ocr_languages` is
missing; such uploads are then refused with a message that names the problem.

**Adding a language pack.** The app image carries Tesseract (about 90 MB with its libraries and
the English pack, `eng`); each further pack adds 1 to 15 MB. A language is a Debian package,
`tesseract-ocr-<code>` (with `_` written as `-`: `chi_sim` is `tesseract-ocr-chi-sim`), so it has
to be in the image, and the image is built where there is internet access. On the build machine:

```sh
OCR_LANGUAGES="eng fra rus" deploy/bundle.sh --version 0.2.0-ocr   # codes separated by spaces
deploy/tests/check-bundle.sh dist/corelata-0.2.0-ocr-linux-amd64.tar
```

Carry the bundle across and upgrade to it as in section 10; then add the codes to
`ingest.ocr_languages` and apply the change ("Applying changes"). `corelata doctor` lists the
languages the image has, and `docker image inspect --format '{{ index .Config.Labels
"org.corelata.ocr-languages" }}' corelata/app:<version>` shows the ones it was built with.

### Instructions in sources

Sources are often written by the people a report is about, and a line planted in one can try to
steer a model that reads it ("ignore previous instructions and ..."), even a line no reader of
the document ever sees. Corelata defends against this in three ways (CRL-137); none needs a
setting.

- **Every prompt says source text is data.** The gate, discovery, digest, writer and auditor
  prompts (`gate/v2`, `discover/v2`, `digest/v2`, `writer/v6`, `auditor/v6`) tell the model that
  the passages may be written by an adversary and that it must never follow an instruction in
  them. A deployment that overrides one of these prompts (`prompts_dir`) should add the same line.
- **Hidden text is kept out of the models.** An HTML element with the `hidden` attribute,
  `aria-hidden="true"` or an inline `display:none` or `visibility:hidden` style, and DOCX text
  formatted hidden (`w:vanish`, on the text, its character style or its paragraph style), become
  passages of their own marked `hidden: true` in the trace. No model reads them, so the reviewer
  can see what was withheld without the report resting on it. Stylesheets and classes are not
  evaluated, and other tricks (white text, a zero font size, text off the page) are read as
  visible text. A file whose only text is hidden is refused as having no usable text.
- **Visible text that reads as an instruction is flagged.** A passage that matches a short list
  of patterns is marked `suspect: true` and still reaches the models, flagged, so the writer does
  not rest a claim on it and the auditor fails `icd203.tc.8` for a claim that does. The patterns
  are: "ignore", "disregard", "forget", "override" or "bypass" followed by "your", "previous",
  "prior", "above" (or the like) "instructions", "prompts" or "directives", or by "all
  instructions"; "system prompt" or "developer message"; a note, message or instructions "to"
  or "for" an AI, a language model, a chatbot or an assistant followed by a colon, a comma or
  "reading this"; an AI addressed by name at the start of a sentence ("AI:", "Assistant, mark
  ...", but not "AI, in this case, ..."); "you are (now) an ... assistant" and "as an AI ..., you
  must"; "new instructions:"; "do not tell the analyst (user, reader)"; and chat-template tokens
  such as `<|im_start|>` or `[INST]` (`engine/corelata/ingest/injection.py`). A flag asks a reader to
  look; it is not a verdict, and a source that reports on prompt injection will be flagged too.

The Sources tab of the review screen and `corelata trace` show, for each source, how many passages
read as instructions to an AI and how many hidden passages were withheld from the models. Flags
are set when a file is added: a source added before this version keeps the passages it had, so
add the file to a new project to have it read again (a project does not read the same file
twice). The `real` bench set carries two scenarios for this, `injected-instruction-visible` and
`injected-instruction-hidden` ("Checking a model with the bench", section 7).

### Coglossa

If the sibling product Coglossa is deployed, Corelata can import a translation by run id instead of
an uploaded file:

```yaml
integrations:
  coglossa: { base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY }
```

`base_url` is Coglossa's root URL: an `http://` or `https://` address with a host and, if
Coglossa sits behind a path prefix, that prefix, but no query string or fragment, and no path
that ends in `/api` or names Coglossa's own `/api/health` or `/api/runs/…` (Corelata adds those
itself). A value of another shape is refused when the configuration loads, naming
`integrations.coglossa.base_url`.

Corelata then asks Coglossa's API for the run's export (the translation and its guide, when it has
one) and adds it to the project like an uploaded export, passing the signed-in user's name along
when `auth` is `trusted_header`. The containers must be able to reach `base_url`; Corelata and Coglossa are separate Compose projects, so a service name such as `coglossa-api` does not resolve from Corelata's containers unless you join them to a shared network. Use the host's address or `host.docker.internal:<port>` (the port Coglossa publishes) instead. Without this
section the import answers that the integration is not configured. An unset key variable is refused when the configuration loads, so the API and worker do not start until it is set. `corelata doctor` reports an empty key variable, a key Coglossa rejects, and an unreachable or wrong URL.

### Settings for the hosted demo only

The configuration also accepts a few settings that only Bonham's hosted demonstration uses
(`deploy/hosted/`, not part of the bundle): `storage.kind: s3` with a `bucket`,
`worker.kick_url`, `worker.kick_token_env` and `worker.extra_headers_env`, and
`auth.proxy_secret_env`. Every one is off unless set, and none is needed here: leave them out.
Files stay on the `storage.path` volume, the worker runs all the time, and your reverse proxy is
the only way in. The app image carries no S3 client, so `storage.kind: s3` stops the API and the
worker at start on this install ("S3 storage needs the s3 extra") rather than storing files
anywhere else. The hosted demo is a separate deployment at a `*.vercel.app` address with the
logins `people-first` and `ci`; it uses its own database and bucket in a shared Supabase project
and never touches Coglossa's database or bucket. `deploy/hosted/README.md` describes it.

### Applying changes

The configuration is read when a service starts. After editing `config/corelata.yaml` or `.env`:

```sh
docker compose up -d --wait --force-recreate migrate api worker
```

The worker is stopped first and gets up to 5 minutes to finish the stage it is running; a run that
is still unfinished then is started over from the beginning by the stalled-job requeue. `migrate`
runs before `api` and `worker`, and it validates the configuration. If the file is invalid,
`migrate` fails and `api` and `worker` stay down; the reason is in `docker compose logs migrate`.
Fix the file and run the command again.

## 6. Users, access and the reverse proxy

With `auth: { mode: none }` (the default) there are no users: **anyone who can reach the port can
use Corelata**, read every project and start runs on your model servers. Use it only on a host
whose port nobody else can reach.

For a team, put a reverse proxy in front that signs people in (LDAP, SSO, basic authentication)
and passes the user name in a header, and tell Corelata to trust it:

```yaml
auth: { mode: trusted_header, header: X-Remote-User }
```

Every request must then carry the header; one without it is refused with 401. Corelata records
the name as the actor on runs and reviews. It trusts the header completely, so the API port must be
reachable **only** from the proxy. Bind it to the loopback address by adding to `.env`:

```
CORELATA_HTTP_BIND=127.0.0.1
```

and apply it (section 5, "Applying changes"). An example for nginx on the same host, with basic
authentication:

```nginx
server {
    listen 443 ssl;
    server_name corelata.example.org;
    # ssl_certificate ... ssl_certificate_key ...

    auth_basic           "Corelata";
    auth_basic_user_file /etc/nginx/corelata.htpasswd;
    client_max_body_size 200m;                 # at least api.max_upload_mb

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_set_header   X-Remote-User $remote_user;
    }

    location /api/runs/ {                      # progress is a server-sent event stream
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_set_header   X-Remote-User $remote_user;
        proxy_buffering    off;
        proxy_read_timeout 1h;
    }
}
```

Without `proxy_buffering off;` the writing page of a running report stays empty until the run
ends. The proxy must set `X-Remote-User` itself, overwriting anything the client sent.

If the proxy has a sign-out address that ends its session when it receives a POST, tell
Corelata where it is and the header shows **Sign out**, a form that posts there:

```yaml
auth: { mode: trusted_header, header: X-Remote-User, logout_url: /oauth2/sign_out }
```

`logout_url` is a site path starting with a single `/` or an `http://` or `https://` URL; any other
value (a `javascript:` address, a backslash, a space) makes the configuration invalid and
`migrate` fails. It is operational (not part of `config_hash`, so runs are unaffected); apply it
as in section 5, "Applying changes". Without it no Sign out is shown, which is right for basic
authentication, where the browser keeps the password until it is closed.

### Content-Security-Policy

Every response from Corelata carries `X-Content-Type-Options: nosniff`,
`Referrer-Policy: same-origin` and `X-Frame-Options: SAMEORIGIN`, so no other site can show the
app in a frame and trick a signed-in analyst into clicking **Accept**. Every answer under `/api/`
except `/api/health` also carries `Cache-Control: no-store` (the progress stream:
`no-cache, no-store`), so report, source and trace text is never written to the browser's disk
cache on a shared workstation; the liveness check stays cacheable for monitors, and the app's own
files keep their caching (`no-cache` for the page, a year for the hashed assets). Leave these
headers in place at the proxy.

The app's pages carry no `Content-Security-Policy` of Corelata's own; an HTML report or export
(the report link, `report.html`) carries `Content-Security-Policy: sandbox; default-src 'none';
style-src 'unsafe-inline'; frame-ancestors 'none'` and `X-Frame-Options: DENY`, so a report opened
at the app's address runs no script, loads nothing but its own stylesheet and cannot be framed,
not even by the app (a proxy that replaces Corelata's policy with one allowing `frame-ancestors
'self'` lets the app's own address frame it again, since browsers then follow that policy over
`X-Frame-Options`; other sites still cannot). The review screen shows the report inside a sandboxed frame that carries its
own policy (`default-src 'none'`; its one script and its highlight style bound by a nonce; the
report's stylesheet allowed by its SHA-256 hash; no other inline script or style), so nothing in
a report can load or send anything.

If your proxy adds a `Content-Security-Policy` header to every response, the frame inherits that
policy too. A policy whose `script-src` or `style-src` lacks `'unsafe-inline'` blocks the frame's
script and the report's stylesheet: the report still shows, but clicking a claim no longer
highlights it, and the analyst sees no error. The same happens when the policy also lists a nonce
or a hash in `script-src` or `style-src`: browsers then ignore `'unsafe-inline'`, and the frame's
own nonce is generated in the browser, so no proxy policy can name it. If a site policy is
required, start from this one, which Corelata's end-to-end tests run the review screen behind
(`api/csp_proxy.py`):

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'" always;
```

and check in the browser's developer console (F12) on a review screen that no "Refused to execute
inline script" or "Refused to apply inline style" message appears.

With nginx's `add_header`, as in the sample, the report keeps its own policy as well and the
browser enforces both. A proxy that replaces the header instead (Caddy's `header` directive,
Traefik's headers middleware, nginx with `proxy_hide_header`) drops the report's `sandbox`
policy: there, leave `Content-Security-Policy` alone on `/api/` responses. The sample policy does
not add `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` or `Cache-Control`, since
Corelata sends them; its `frame-ancestors 'self'` agrees with `X-Frame-Options: SAMEORIGIN`
(browsers that know `frame-ancestors` follow it and ignore `X-Frame-Options`).

## 7. Running it

```sh
docker compose ps                 # state and health of every service
docker compose logs -f worker     # follow the worker (JSON lines)
docker compose logs --tail 100 api
```

| Service | What it does |
| --- | --- |
| `postgres` | The database: projects, runs, traces and the job queue. |
| `migrate` | Runs once at every start: creates or upgrades the schema, then exits (`Exited (0)`). |
| `worker` | Executes the queued runs and discoveries: model calls, audit loop, exports. |
| `api` | Serves the web app and the HTTP API on port 8080. |

Services restart on their own after a crash or a reboot (`unless-stopped`); logs rotate at 50 MB
times 5 files per service.

The command line is inside the containers. These work against the running stack:

```sh
docker compose exec api corelata status <run-id>        # state, stages, usage; add --json
docker compose exec api corelata cancel <run-id>        # a running run stops after its stage
docker compose exec api corelata review <run-id> --accept
docker compose exec api corelata review <run-id> --return --note "Say more about the tariffs"
docker compose exec api corelata export <run-id> --out /data/files/export-<run-id>
docker compose exec api corelata doctor
```

To check a configuration file before you put it in place, copy it into the container's files
volume (`config/` is mounted read-only at `/etc/corelata`) and point doctor at it:
`docker compose cp corelata.new.yaml api:/data/files/corelata.new.yaml`, then
`docker compose exec api corelata doctor --config /data/files/corelata.new.yaml`. Remove the
copy afterwards (`docker compose exec api rm /data/files/corelata.new.yaml`).

`review --return` queues a new run that carries the note as guidance for the writer. If that
run fails, is cancelled or stops at the gate, the report can be returned again (or accepted);
while the rerun is queued, running or completed, a second return is refused and names it
(a rerun that is created but not yet running already spends the return). `export` writes the
run directory (trace and the report in every format) to a path inside the container;
`/data/files` is the files volume, so use a path there and copy it out with `docker compose cp`.
The web app offers the same downloads in the review's **Download** menu.

An accept is final: `review --return` (or **Return with note…**) on an accepted run is refused
with "run … was accepted; start a new run to change it". Start a new run on the same sources
instead.

**A run whose worker died.** Once the worker that took a run has sent no heartbeat for
`worker.stalled_after_s`, the run's page no longer says "it keeps going": it says the process
writing the report stopped responding, that the report starts over when it is running again,
and offers **Stop now…**, which ends it at once. `corelata status <run-id>` prints `its worker
stopped responding; it starts over when a worker is running again, or cancel it to end it now`
(CRL-69). Any running worker re-queues the job within a minute or so of that threshold, so the
message lasting longer means no worker is running: check `docker compose ps worker`.

**Cancelling a run whose worker died.** A cancel (`corelata cancel <run-id>`, or **Stop writing…**)
stops a running run at its next stage. If the worker running it was killed or its host went
down, the run's job is still marked as taken by that worker: the first cancel only records the
request. The command prints `run <id>: cancel requested; it stops after the current stage`, and
on the screen the **Stop writing…** button is replaced by the text "Stopping after the current
step…". A cancel ends the run at once, and closes its job so it never runs again, when the
worker holding the job is gone: its heartbeat is older than `worker.stalled_after_s` (default
900 s; the demo configuration sets 120 s), or its worker row was deleted. From then on the
screen says the worker stopped responding and offers **Stop now…**, `corelata status <run-id>`
prints `cancel requested, but its worker is gone; cancel it again to end it now`, and the run's
progress carries `worker_gone: true` (CRL-49). Press **Stop now…**, or run
`docker compose exec api corelata cancel <run-id>` again (it prints `run <id> cancelled`). The run also ends on its own once any running worker requeues the dead worker's job
after `worker.stalled_after_s`: the requeued job sees the cancel and ends the run, and a second
`corelata cancel` then answers `error: run <id> is already cancelled` and exits with status 2.
A worker that comes back, or is still alive after all, stops at its next write and leaves the run
cancelled; it records nothing more for the run, so the model calls and token usage of the stage
it was in are not kept; its log line says how many model calls and tokens that was. It leaves the
closed job alone and says at INFO that the job was "left as it is: it was closed meanwhile". The
same holds for a run a requeued job started over on another worker while the first was still
alive: the first stops at its next write, logs at INFO that the run "was started over elsewhere",
and leaves the job to the worker that now holds it ("left as it is: another worker holds it"),
so the run is never executed twice past that write. If the worker's silent-job requeue had listed the job just before the cancel
closed it, the worker's log says at INFO that the job "was closed before it could be re-queued;
skipped". A worker that is merely slow keeps sending its heartbeat and is never cancelled under
its run.

**The web app.** Every screen has a header (the name, which leads to New report; the theme
toggle ☾ / ☀; **Help**, also on `?`; **Settings**; the signed-in name and **Sign out** when the
proxy provides them) and a sidebar: **+ New report**, then the projects, newest activity first,
grouped Today, This week and Earlier, each with one status: "… writing", "● N waiting for review",
"! needs attention" (its latest report could not be written), "⚠ not supported", "✓ accepted",
"↺ returned", "■ stopped", or "no reports yet". The sidebar's foot shows the version. Below 900 px
wide the sidebar opens from the header's **Your projects**. **New report** asks which project the
report is for, or creates one. A project's page holds its **Sources** (drop files or click to
choose; **Add as** documents or Coglossa exports; a file over `api.max_upload_mb` or of another
type is marked and not sent; **Upload** sends the others one after another), the **Value
statement** with **Suggest value**, **More options** (team profile, revision rounds), **Write the
report**, and the project's **Reports**. **Writing the report** lists the steps, each with ✓ done,
● now, ! failed or ○ not yet; **Details** holds each step's duration and error and the model usage;
the page can be left while it writes. The review shows the report beside four tabs: **Claims** (a
claim's passages and where the report cites it), **Standards** (each rule under Not met, Minor
issues, Met and not applicable, or Advisory, with its severity, why and its history), **Process**
and **Sources** (the stages, models and hashes, in the engine's words); **Accept**, **Return with
note…** and **Download** are in its header. "Not met" is what the engine counts as open: a rule
whose latest verdict is a fail at blocking or major severity, the rules the banner's and the
writing page's "N standards not met" count and a revision round tries to fix. A fail at minor
severity does not keep a report open, so it is listed under **Minor issues**; a report with only
minor issues is clean, its pill says "✓ Meets the standards", and the banner reads "Every
blocking and major standard that could be checked was met. 1 minor issue is listed under
Standards." (R-M18-27). **Settings** has the theme, the installation's status in one plain sentence
(**Run a full check** sends a test completion to each model; a check run within the last 30 s,
from any browser, is shown again rather than repeated, CRL-112) and **Technical details** (version,
sign-in mode, upload limit, default pack and team profile, the packs and their profiles, and every
doctor check by name). The theme follows the computer until someone picks one, per browser.

**The HTTP API.** Everything the web app does goes through the HTTP API under `/api`, which a
script can call as well (uploads, runs, reviews, exports). `GET /api/openapi.json` describes
every route; it needs the same sign-in as the rest (section 6), while `GET /api/health` needs
none. Listing runs needs the project: `GET /api/runs?project_id=<id>` answers
`{"runs": [...], "next_before": ...}`, newest first, 100 at a time (`limit`, at most 500); pass
`before=<next_before>` for the next page. Without `project_id` it is a 422. Free text has limits,
because it goes into every model prompt and the trace: a run's `value_statement` at most 4,000
characters and its `extra_guidance` at most 8,000, a review's return `note` at most 8,000 (it
becomes the revised report's guidance) and a discovery's `audience_hint` at most 500. Longer text
is a 422 that names the limit; the web app's fields stop at the same lengths and show a count
near them. A script that sent longer text before these limits must shorten it. Each return adds
its note to the guidance the run already carries, so a chain of returns stops once that guidance
would pass 24,000 characters: the return is a 422 that says to start a new report. `corelata run`
and `corelata review` (accept or return) apply the same limits.

**Checking a model with the bench.** `corelata bench` plays a set of scenario files against the
configured models and reports how often the run did what the scenario expects: gate verdict,
failing rules, final state. Two sets ship with the engine. `synthetic` (the default, thirteen
scenarios) was written for the synthetic model and steers it with markers in the source text; a
real model disagrees with it often, and that says little about the model. `real` (twelve
scenarios) has short, plausible sources and expectations a good model meets, stated as ranges
("thin or sufficient", "these rules must pass"); use it when you change a model, a prompt
override or the pack, and compare the numbers with the previous run. Two of them plant an
instruction to AI systems in a source (CRL-137): `injected-instruction-visible` in plain text,
which a good model reads flagged and neither obeys nor rests a claim on, and
`injected-instruction-hidden` in hidden HTML, which no model receives; both fail if the title or a
key judgment carries the planted code word (`report_excludes`), and both check which passages
ingest marked hidden and suspect (`hidden_units`, `suspect_units`). A model that disagrees on the
visible one obeys text it was told is data:

```sh
docker compose exec api corelata bench --scenarios real --out /data/files/bench-real-$(date +%F)
docker compose exec api corelata bench --scenarios real --only conflicting-rail-figures --repeat 3
docker compose exec api corelata bench --concurrency 4 --store-io --out /data/files/bench-$(date +%F)
```

The table's `gate` column shows the gate's verdict (`supported · thin`, `rejected ·
insufficient`) and, when it disagrees with the scenario, the gate's first reason. An interrupted
bench leaves a `bench.json` with the runs that finished. A run whose last audit degraded
leaves the rule sets unscored and counts as a disagreement. A run that could not execute shows
`err` and the start of its error in the table, and the whole error under `errors` at the end.
The `real` set names `icd203-base` rule ids, so a deployment with a replaced pack will see
"not in pack" mismatches and should write its own set. `--scenarios DIR` plays a directory of
your own (for a directory called `real` or `synthetic`, write `./real`).

Exit 0 means every run matched, 3 that some disagreed (listed at the end of the report), 1 that a
run could not execute (the scenario's profile is missing, for example). The bench is a
measurement, not a gate. A run of either set makes several dozen model calls.

**Where the data is.** Everything lives in two Docker volumes, `pgdata` (the database) and `files`
(uploaded sources, reference documents, exports). They belong to the Compose project `corelata`,
not to the directory, so moving or renaming the bundle directory keeps them (`docker volume ls`
shows them as `corelata_pgdata` and `corelata_files`). `config/` and `.env` are in the directory.

**Housekeeping.** A task in the worker runs every minute: it re-queues the jobs of a worker that
stopped responding (after `worker.stalled_after_s`), marks runs whose job was lost as failed, and
fails discoveries past their limits: not started `worker.discovery_start_deadline_s` after they
were created, or not finished `worker.discovery_deadline_s` after the worker started them.
The worker deletes a job when it succeeds; failed, cancelled and aborted jobs stay in the queue table `procrastinate_jobs`, so it grows slowly. The worker deletes closed jobs older than `worker.job_retention_days` (default 30) every night; to clear them by hand, or with a different window, run:

```sh
docker compose exec -T postgres psql -U corelata -d corelata -c "
WITH old AS (
  SELECT j.id FROM procrastinate_jobs j
  WHERE j.status IN ('succeeded', 'failed', 'cancelled', 'aborted')
    AND COALESCE(j.scheduled_at,
          (SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id))
        < now() - interval '30 days'),
gone AS (DELETE FROM procrastinate_periodic_defers WHERE job_id IN (SELECT id FROM old))
DELETE FROM procrastinate_jobs WHERE id IN (SELECT id FROM old)"
```

This removes only closed jobs older than 30 days; it never touches runs, reports or traces.

### What the analyst knows about a source

The writer fills in each source's descriptor, reliability note, date of information, origin and
access from the text alone. An analyst who knows better can state any of them (CRL-138): on the
new report page, **Details** next to a source; in the API, the optional form fields
`descriptor`, `reliability_note`, `date_of_information`, `origin` and `access` of an upload, or
`PATCH /api/projects/{id}/sources/{sid}` with any of them (an empty string clears one); on the
command line:

```sh
docker compose exec api corelata ingest /data/files/port.pdf --project "Black Sea" --origin "Varna Port Authority"
docker compose exec api corelata source set <source-id> --project "Black Sea" --access direct --date-of-information "August 2026"
docker compose exec api corelata source set <source-id> --project "Black Sea" --origin ""   # back to the model
```

A stated descriptor must be one of the default pack's source descriptors (any of its profiles'
count) and a stated access one of its `source_access` terms; a run checks them again against the
lexicon it uses and is refused, naming the source, when its profile does not allow one. Every
stated value goes into the report's source entry exactly as given, in place of what the writer or
the reviewer wrote (the date, origin and access only when the pack asks for them); the trace
records each value the engine wrote over (`stated_overrides`, `docs/trace-format.md`) and the
review screen's Sources tab marks each value "stated by analyst" or "inferred by model". A run
keeps the values it was queued with: an edit changes reports started after it, and a return. A
check (`kind: check`) does not apply them: it audits the report as its author wrote it.

### Removing a source or a project

A file uploaded by mistake, or a whole project that should not exist, is removed from the command
line. The web app and the HTTP API have no delete; this is an operator's job. A removal cannot be
undone, except by restoring a backup (section 9), and the backups you already have still hold what
it removed: delete or age out those too if the data must be gone everywhere. A bucket with
versioning turned on keeps the deleted objects' earlier versions; expire them with a lifecycle rule
if they must go too.

Find the source's id first. `corelata sources` lists a project's sources, oldest first, with how
many runs used each:

```sh
docker compose exec api corelata sources --project "Port study"
# 3f6c…-…  2026-11-20 09:14  used by 0 runs      wrong-file.pdf
```

Then delete it, or the whole project:

```sh
docker compose exec api corelata delete-source <source-id>
docker compose exec api corelata delete-source <source-id> --with-runs
docker compose exec api corelata delete-project "Port study"
```

Each command first lists what it will delete (every source, run and discovery by id, and the
stored-file prefixes) and asks you to type `delete` (for a source) or the project's name (for a
project). Without a terminal it stops with "this needs a terminal to confirm; add --yes to delete
without asking": pass `--yes` from a script. Anything else typed, or Ctrl-D, answers "not
confirmed; nothing was deleted" and exits with status 1. If what it would delete changed between
the listing and your answer (someone started a run on the source meanwhile), it deletes nothing
and says so; run it again.

**What `delete-source` removes.** The source's row and its text units; every row that shares its
stored file (a Coglossa export that carries a translation guide is two sources with one file, and
they go together); the file itself (`projects/<project-id>/sources/<id>/` on the files volume or in
the bucket); and every discovery that read it, since its suggested statements were drawn from it.

**A source a run used is refused.** Its reports quote it, so the command stops with
`error: source <id> (<name>) was used by N runs: <ids>; add --with-runs to delete those runs and
their reports too` and exits with status 2. With `--with-runs` those runs go as well: each run's
report, trace, drafts, claims, audit findings, model calls, review history and exports, and its
files under `runs/<run-id>/` (the exports and the run's copy of the reference document). A run
that only names a deleted run as its parent (a run queued with `--parent-run`) but did not use the
source stays; it loses the link. A later run that was given a deleted report among its earlier
accepted reports keeps, in its own trace, the title and key judgments it was given. A report uploaded to be checked ("Checking an existing report" below) counts as used by its
check runs in the same way: deleting it is refused without `--with-runs`, and with it the check
runs go.

**What `delete-project` removes.** The project and everything in it: its sources and their files
(`projects/<project-id>/`), its runs with everything above (`runs/<run-id>/` for each) and its
discoveries. The name is free again afterwards.

**Work in flight is refused, never stopped.** If a run the command would delete has not ended
(queued or writing), it stops with `error: 1 run not ended yet: <id>; cancel (corelata cancel
RUN_ID) and wait until it has ended, then try again` and exits with status 2. Cancel the run,
wait for `corelata status <run-id>` to say `cancelled`, then delete. A discovery that has not
ended is refused the same way; it ends by itself, at the latest by its deadline
(`worker.discovery_deadline_s`).

**While it runs** the project is locked: an upload or a new run in that project waits until the
removal has finished. A progress page open on a deleted run shows that the report was deleted.
The database rows are deleted first, then the stored files, in one transaction that commits only
after both: if the database refuses (a review returning one of the runs at that moment, say),
nothing is deleted; if the files volume or the bucket fails, no row is deleted and the command says
what failed (`error: cannot delete …`, status 2), though some files may already be gone; if it
stops after the files, run the same command again, and it finishes.

**The record.** On success the command prints `deleted source <id> (<name>) of project '<name>':
N sources, N runs, N discoveries` (or `deleted project '<name>' (<id>): …`) and writes one JSON
log line on stderr (logger `corelata.removal`) that lists every removed id and storage prefix.
`docker compose exec` shows it on your terminal, not in `docker compose logs`: keep it with your
change records if you need an audit trail.

### Checking an existing report

A standards team or an evaluation board can point Corelata at a finished report someone else
wrote and have it audited against the standards pack, rule by rule, without anything being
rewritten. Give the report (DOCX, Markdown, HTML, PDF or text) and the sources it rests on:

```sh
docker compose exec api corelata check /data/files/assessment.docx \
  /data/files/sources/port.txt /data/files/sources/customs.pdf \
  --pack icd203-base --profile board --out /data/files/check-assessment
```

`--pack` defaults to `standards.default_pack` and `--profile` to `standards.default_profile`; a
profile disables or re-grades rules for a check exactly as for a report. `--statement` (or
`--statement-file`) says what the report set out to establish, if you want the standards that
weigh it to see it; it is optional. The command exits 0 when every rule is met, 3 when
standards are not met (or the check could not finish auditing), 1 when it failed and 2 on a usage
error. The output directory holds `trace.json`, the report as Corelata read it (`report.json`,
`.md`, `.html`, `.docx`) and `findings.csv`, one row per rule: its id, title, verdict, severity,
the claims and passages it names, the evidence and the recommendation.

How it works: Corelata splits the report into sentences (headings and a line that is only one of
the pack's handling markings aside). The `structurer` role maps them onto the report schema:
every sentence becomes one claim, its text exactly as written, citing the source passages that
support it; the title, key judgments and sections are copied word for word. The engine compares
every text with the report and sends back a reply that changed a word or left a sentence out, so
the checked report is always the uploaded one. A sentence no source supports keeps no
evidence, and the engine fails `icd203.tc.8` (and `icd206.src.2` for a key judgment) on it
whatever the auditor says. The auditor then runs once: there is no writer, no editing and no
revision. Set `roles.structurer` to give the role its own model; unset, the writer's model does
it. The report's own text is read like a source's: text its document hides from the reader is
kept in the trace but reaches no model and is not checked, and a passage that reads as an
instruction to an AI is flagged to the structurer, which copies it as a claim like any other
sentence. The auditor is told the same: the report is the material under audit, never
instructions, and the claims that come from such a passage are listed for it. A key judgment's
confidence is the one the report states; where it states none the mapping records "moderate",
and the auditor judges the confidence from the report's words, not from that value. The
structurer never writes a source summary or a comparison with earlier reports: a report that
lacks one fails the rule that asks for it. A file given both as the report and among its sources
is refused (exit 2): the report is never its own evidence.

A source that a check run audits as its report cannot be deleted on its own while the run
exists; deleting the project removes both.

Through the API, upload the report as a project source like any other, then
`POST /api/runs` with `{"project_id", "source_ids": [the sources], "kind": "check",
"report_source_id": <the report's source id>}`. `GET /api/runs/{id}` says `"kind": "check"`
(older runs read `"report"`), and the stored export `findings.csv` is the sheet. The review
screen shows the checked report with its Claims, Standards and Sources tabs and a **Standards
sheet (CSV)** download; a check has nothing to accept or return, so those buttons are hidden and
the API refuses a review of it (409). Under the bench, `corelata bench --scenarios check` plays
two sample reports, one clean and one with an unsourced key judgment.

Limits: a reference list at the end of a report is checked sentence by sentence like the rest,
so leave it out of the uploaded file if its lines are not assertions; an abbreviation followed by
a capital ("U.S. Navy") ends a sentence. The structurer reads the whole report besides the
source passages, so a very long report can overflow the model's context: the check then fails
cleanly (state `failed`, exit 1) and nothing is delivered; split the report or give the
structurer a model with a larger context (`roles.structurer`).

## 8. Backups

```sh
./backup.sh [DIR]
```

Run it from the bundle directory while Corelata is running. It writes two files into `DIR`
(default `./backups`) with the same timestamp:

- `corelata-db-<stamp>.dump`, the database (a `pg_dump` custom-format dump);
- `corelata-files-<stamp>.tar.gz`, the files volume.

Together they hold everything Corelata stores. They contain your sources and reports, so the
script makes them readable only by you; keep them private. A backup is only complete when both
files are there: the script keeps neither if one fails.

A crontab entry (one line), at 02:00 every day, keeping 14 days:

```
0 2 * * * cd /opt/corelata && ./backup.sh /srv/backups/corelata && find /srv/backups/corelata \( -name 'corelata-db-*.dump' -o -name 'corelata-files-*.tar.gz' \) -mtime +14 -delete
```

An upgrade unpacks a new directory, and the cron entry keeps pointing at the old one. Update the path in the crontab at each upgrade, or point a stable symlink at the current release directory (for example `ln -sfn /opt/corelata-1.0.1 /opt/corelata`, which the cron line above assumes) and move the link as the last step of an upgrade.

The files backup streams the volume through a one-shot container, which is slow for very large volumes (many gigabytes); run it off-hours.

**What a backup does not hold:** `config/corelata.yaml`, `config/packs/` and `.env`. They are
yours and small; keep a copy beside the backups (`cp -R config .env /srv/backups/corelata/`) and
update it whenever you change them. Copy the backups off the host as well.

A backup does not hold the bundle tarball either. A restore on a new host needs the bundle of the version that made the backup (or a newer one), and an air-gapped site cannot download it again: keep the `corelata-<version>-linux-amd64.tar` and its `.sha256` with the backups.

## 9. Restore

```sh
./restore.sh corelata-db-<stamp>.dump corelata-files-<stamp>.tar.gz
```

The database dump comes first, then the files archive. The script asks you to type `restore` to
confirm, which needs an interactive terminal; from cron or any automation it stops with "this needs
a terminal to confirm; add --yes", so pass `--yes` there. It stops `api` and `worker`, replaces
**all** current data with the backup's (the database in a single transaction, so a bad dump leaves
the current data in place; the files volume only after the database restore succeeded) and starts
the stack again. Ctrl-C or a TERM leaves no temporary file and restarts whatever the script
had stopped, but it can arrive between the two steps: the database may then be replaced while the
files volume is not, or is only partly refilled. The script says so ("restore.sh: interrupted
after stopping Corelata; the database may be restored but not the files. Run ./restore.sh again
with the same two files."). Run `./restore.sh` again with the same two files until it finishes.

restore.sh works on the `public` schema only, which is where everything Corelata and its job queue create lives. If the database holds other schemas (an extension you added, a reporting schema), the script refuses before stopping anything and names them; move or drop them first.

If the script cannot list the database's schemas it stops before changing anything and prints
psql's own message under `psql said:` (for example a refused connection or a database that does
not accept connections).

**On a new host:**

1. Unpack the same bundle or a newer one, and run `./install.sh`.
2. Copy `config/corelata.yaml`, `config/packs/` and `.env` over the freshly created ones (a
   `.env` with the demo's `COMPOSE_FILE` line, section 4, restores the demo stack).
3. `docker compose up -d --wait`
4. `./restore.sh --yes corelata-db-<stamp>.dump corelata-files-<stamp>.tar.gz`
5. `docker compose exec api corelata doctor`

A newer bundle brings the schema forward by itself: `migrate` runs when the stack restarts. A
lost `.env` is not a problem: the dump holds no database roles or passwords, so the `.env` that
`install.sh` creates works with a restored database (add back any model-server keys). Without
your `config/corelata.yaml` you configure again from the example.

## 10. Upgrades

1. In the old directory, take a backup outside the bundle directories, which an upgrade leaves
   behind: `./backup.sh /srv/backups/corelata` (any directory outside the bundle directories
   works; create it first and make it writable for you, for example
   `sudo install -d -o "$(id -un)" -m 700 /srv/backups/corelata`). Keep the old bundle's
   `corelata-<version>-linux-amd64.tar` and `.sha256` too: going back needs both.
2. Check and unpack the new bundle beside the old one (section 3, step 1).
3. Copy `config/corelata.yaml`, `config/packs/` and `.env` from the old directory to the new one.
4. In the old directory: `docker compose down` (the data volumes stay).
5. In the new directory: `./install.sh`, then `docker compose up -d --wait`, then
   `docker compose exec api corelata doctor`.
6. If a crontab entry runs `backup.sh`, point it at the new directory (or move the symlink it uses; section 8).
7. Once the new version works, remove the old image: `docker image ls corelata/app` lists them,
   `docker image rm corelata/app:<old version>` removes one. `postgres:16-alpine` is one tag: a
   newer bundle may load a newer image under it, which leaves the old one untagged (`<none>` in
   `docker image ls`): find its IMAGE ID there and remove it with `docker image rm <IMAGE ID>`.

`migrate` upgrades the database schema before `api` and `worker` start, so the new version never
sees an old schema. Your packs are untouched: the new version uses what is in `config/packs/`.

**From 0.1.3.** Migration 0005 runs inside `migrate` and changes no schema. It deletes `return`
events whose rerun was never linked (a return interrupted under 0.1.3) and rewrites every
reviewed run's stored decision to include the rerun's outcome and the reviewer's note. A report
whose only rerun failed, was cancelled or was gate-rejected, which 0.1.3 treated as spent, can
now be returned again or accepted. A restore of a 0.1.3 backup into 0.1.4 runs the migration
too (the final `docker compose up -d --wait` restarts `migrate`).

**From 0.1.4.** Reports accepted before the upgrade can no longer be returned: start a new run to
change one.

**From 0.1.5.** Migration 0006 runs inside `migrate`, before `api` and `worker` start, and adds
one index to the run table (`ix_run_project_created`, a plain `CREATE INDEX`: it makes the run
list faster and changes no data). A restore of a 0.1.5 backup into 0.1.6 runs it too. A backend
`base_url` with a query string or a fragment, which never worked, now stops `migrate` with the
reason (`docker compose logs migrate`): remove the query and put any key in the variable
`api_key_env` names (section 5). Discoveries still queued `worker.discovery_start_deadline_s`
(default 60 minutes) after they were created, or still running `worker.discovery_deadline_s`
(default 10 minutes) after the worker started them, are failed when they are next read, or by the
worker's next sweep. Both settings are optional; the example configuration lists them.

**From 0.1.8.** A backend `base_url` without `http://` or `https://` and a host, or one that
already ends in `/chat/completions` or `/models`, and an `integrations.coglossa.base_url` that is
not Coglossa's root URL (section "Coglossa"), now stop `migrate` with the reason (`docker compose
logs migrate`). None of them worked before: Corelata's requests went to the wrong address.

Migration 0007 also runs inside `migrate`, before `api` and `worker` start, and drops one index
from the run table (`ix_run_project_id`, which `ix_run_project_created` makes redundant; it changes
no data). A restore of a 0.1.8 backup into a newer version runs it too.

Migration 0008 also runs inside `migrate` and adds one nullable column to the run table
(`prior_reports`, the earlier accepted reports a run read; runs made before it read as none). It
changes no data, and a restore of an older backup runs it too. A run reads its project's
accepted reports only once you set `pipeline.prior_judgments.max_reports` above 0 (section 5,
Pipeline; unset, it is 0); `icd203.tc.7` is checked against them only once your pack has the base pack's
`with_prior_reports` block (see the next paragraph).

Migration 0011 also runs inside `migrate`, before `api` and `worker` start, and brings the job
queue's tables and functions to procrastinate 3.12.0: it adds a `lock_mode` column to
`procrastinate_jobs` (every existing job gets `ordered`, the behaviour it had), replaces one
index on that table with another and replaces procrastinate's 3.10 functions with their 3.12
versions. Jobs waiting in the queue are kept and run after the upgrade. It needs the old version
stopped first, as step 4 does: a 0.1.8 worker or API cannot queue jobs once it has run. A restore
of an older backup runs it too.

**New rules in a newer base pack.** The bundle ships its base pack in `config/packs.example/`,
which the installer never copies over your own. See what changed, then merge by hand:

```sh
docker compose exec api corelata pack diff /etc/corelata/packs/icd203-base /etc/corelata/packs.example/icd203-base
```

(On the host: `corelata pack diff config/packs/icd203-base config/packs.example/icd203-base` from a
checkout.) Exit 0 means the two are the same, 3 that they differ; `--json` gives the diff as data.
The same command compares a pack with a profile or with the pack a run actually used. For a
profile, name your packs directory too:
`docker compose exec api corelata pack diff /etc/corelata/packs/icd203-base /etc/corelata/packs/icd203-base --profile-right team-east --packs-dir /etc/corelata/packs`.
A bare pack name without `--packs-dir` or `--config` means the pack built into the image. Runs live in the database, so export the run first
(`docker compose exec api corelata export <run-id> --out /data/files/run-<id>`; the path must be
writable, and `/etc/corelata` is read-only), then
`docker compose exec api corelata pack diff /data/files/run-<id> /etc/corelata/packs/icd203-base`.
The exported directory's `trace.json` carries the snapshot.

Take the rules you want, then run `pack validate` (section 5). Base pack 1.1.0 (CRL-96) adds the
`source_summary` section to `template.yaml`, the `source_access` list to `lexicon.yaml` and the
ICD 206 D.3.d wording of `icd206.src.1`; a pack without them runs exactly as before. Base pack 1.2.0
(CRL-136) adds the `likelihood_alternates`, `unlisted_probability_words` and `confidence_phrases`
lists to `lexicon.yaml`; copy them into a customised lexicon to have the engine check uncertainty
wording.

**Going back.** Migrations only go forward, so an older version cannot run on an upgraded
database. Run `docker compose down` in the new directory, then restore the pre-upgrade backup
from step 1 (in `/srv/backups/corelata`) with `./restore.sh` in the old directory; if you
removed the old image (step 7), run `./install.sh` there first, which loads it again from the old
bundle. That replaces the data, schema included,
with the state before the upgrade and starts the old version.

## 11. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `migrate` did not complete | The configuration or the database is wrong. `docker compose logs migrate` names the problem; fix `config/corelata.yaml` and run the command from "Applying changes". |
| `doctor` fails on a backend or a model | The URL (ends in `/v1`; reachable from a container), the model id (the fix suggests up to five ids the server serves with the same prefix; the whole list is `curl <base_url>/models` from a host that can reach the server; the image has no curl) or `api_key_env` (the variable must be in `.env`; recreate the services). "json_schema request failed: … invalid_json_schema" means the server rejects the schema a run sends: set that model's `structured_output` to `json_object`. A `model <key> auditor schema` line failing with "json_schema request failed" under a passing `model <key>` line means the server accepts the gate's small schema but not the auditor's larger one (one required property per rule): set that model's `structured_output` to `json_object`. "the AuditByRule reply was cut …" is the same as the GateVerdict case (an AuditByRule needs about 60 tokens per rule plus any reasoning): raise `max_output_tokens`, or, when the message says the server's default output limit cut it, set `max_output_tokens` above that default. A request that timed out or overflowed the context is not a schema problem: follow the fix the line prints. The auditor line is absent under `--no-probe` and after a failed test completion. "the GateVerdict reply was cut at max_tokens=N" means the `max_output_tokens` you set for that model cut the reply (a GateVerdict needs about 150 tokens plus any reasoning the model emits first): raise it or unset it. A `json_object` model that answers with JSON that is not a GateVerdict should be set to `structured_output: none`, or replaced by a model that follows a JSON schema. A line that says "works after one repair turn" is a warning, not a failure: the model's first reply was not the requested JSON and its repaired one was; runs work, with a second request on such calls. "did not return the requested JSON …, even after one repair turn" means the repaired reply was wrong too: follow that line's fix. |
| `run ./install.sh first` | `.env` is missing, so there is no database password. Run `./install.sh`, or on an upgrade copy the old `.env`. |
| Port 8080 is taken | Set `CORELATA_HTTP_PORT=8081` (or another) in `.env` and recreate `api`. `CORELATA_HTTP_BIND=127.0.0.1` in the same file publishes the port on the loopback address only (behind a reverse proxy or an SSH tunnel). |
| Permission errors on `config/` | The containers run as uid 10001: `chmod -R a+rX config`. |
| `install.sh` says the bundle is damaged | A file differs from `SHA256SUMS`. Copy the bundle again and check it with `sha256sum -c corelata-<version>-linux-amd64.tar.sha256`. |
| `password authentication failed` in `docker compose logs migrate` | After an upgrade, `.env` was not copied, so `install.sh` wrote a new random password while the existing `corelata_pgdata` volume still holds the old one. Copy the old directory's `.env` into the new one, then run the command from "Applying changes". Do not use `down -v`: it deletes the data. |
| A run stays `created` | The worker is down: `docker compose ps worker`, then `docker compose logs worker`. |
| A run ended `failed` with "no queued job exists" | The queue was unavailable when the run was created; the worker's sweep closed it. Start the run again. |
| The review says "The revised report couldn't be written: …" (or was stopped, or stopped at the value check) | The run a return created ended without a report, often because the model server was unreachable. Fix the cause the message names (`docker compose logs worker`), then use **Return with note…** again (the previous note is offered) or **Accept**. |
| A return is refused with "was accepted; start a new run to change it" | The report was accepted, which is final. Start a new run on the same sources and statement; the accepted report stays as it was. |
| The project page says "Discovery did not start within … and was stopped" | No worker started the discovery within `worker.discovery_start_deadline_s` (default 60 minutes). Either the worker was stopped (`docker compose ps worker`, `docker compose logs worker`), or the worker was busy with runs: discoveries share `worker.concurrency` with runs and are picked first, but wait while every slot holds a run. Start a new discovery; raise `worker.concurrency` or `worker.discovery_start_deadline_s` if long runs keep the worker busy (section 5). |
| The project page says "Discovery did not finish within … and was stopped" | The worker started the discovery, but it did not finish within `worker.discovery_deadline_s` (default 10 minutes): a slow model server took too long, or the worker died while running it (`docker compose logs worker`). Start a new discovery; raise `worker.discovery_deadline_s` for a slow server (section 5). |
| The project page says "Discovery has not finished after 10 minutes" | The server did not end the discovery by its limit. One possible cause is a database clock that differs from the API's (a separate database host); check both hosts' clocks. Reload the page to read it again, or start a new discovery. |
| A report says "Stopping after the current step…" and does not move | Its worker died while running it, or the step is just long; cancelling again is harmless. A cancel ends the run at once when its worker's heartbeat is older than `worker.stalled_after_s` or its worker row was deleted: the screen then offers **Stop now…**, or run `docker compose exec api corelata cancel <run-id>` again. The run also ends on its own once a running worker requeues its job after `worker.stalled_after_s`; a second `corelata cancel` then answers that the run is already cancelled (section 7). |
| `migrate` or `doctor` says `base_url: … must not contain a query string` | Write the server's address and path only (`http://models:8000/v1`) and put a key in the variable `api_key_env` names (section 5). An unquoted `?` inside the shipped `{ base_url: …, … }` form is reported as invalid YAML at the `?` instead; the remedy is the same: remove the query. |
| A run failed with "model server unreachable (…)" | The model server named in the parentheses refused the connection, is not listening, or its name does not resolve from the containers. Check it is up and reachable from a container (`docker compose exec api corelata doctor`: it probes `/models` and prints `backend <name>` as FAIL with `unreachable:` and the error). A TLS certificate the host does not trust also shows as `ConnectError` (for example `CERTIFICATE_VERIFY_FAILED`). |
| `restore.sh` stops with "could not list the database's schemas" | Read the lines under `psql said:` (a refused connection, a database that does not accept connections); start the database (`docker compose up -d --wait postgres`) or fix what psql names, then run the restore again. |
| A report is `findings_open` and lists "Stages incomplete at delivery" (the review's banner says "Delivered without a full check" and names the step) | The auditor or the conveyor could not produce valid output after its repair turn and one retry, so the report was delivered without it. "audit incomplete" means the rules were not checked on the delivered draft (any findings listed are the previous audit's, plus the engine's own unsourced-claim checks on the delivered draft); "conveyance skipped" means the writer's draft was delivered unedited. The writing page shows the failed step and its error. Usually the model is too small for that role: give the role a stronger model, or set `structured_output: json_schema` if the server supports it, then return the report for a rerun. |
| `doctor` or a run cannot reach a model server on the host (`host.docker.internal`) | The server listens on 127.0.0.1 only (Ollama's default), which a container cannot reach, or the host firewall blocks the Docker subnet. Make the server listen on 0.0.0.0 or on the Docker bridge address (for Ollama, `OLLAMA_HOST=0.0.0.0`), or allow the Docker subnet through the firewall. |
| An upload is refused with "needs OCR (needs_ocr)" | The PDF has scanned pages (pictures with no text layer). Set `ingest.ocr: auto` (section 5, "Scanned PDFs"). If it already is, the message says Tesseract is missing or names the language it could not load: run `corelata doctor` and follow its `ocr` line. |
| A profile is refused as a draft | It has `draft: true`. Review it and remove the flag. |
| The web app shows "could not be reached" | The API is down or restarting: `docker compose ps api`, `docker compose logs api`. Behind a proxy, check the proxy too. |
| 401 "missing X-Remote-User" | `auth.mode` is `trusted_header` and the request did not come through the proxy, or the header name differs. |
| A report says the process writing it stopped responding | Its worker died. Any running worker re-queues it within about a minute of `worker.stalled_after_s`; if the message stays, no worker is running: `docker compose ps worker`. **Stop now…** or `corelata cancel <run-id>` ends it at once. |
| Clicking a claim does not highlight it in the report, or the report shows without its layout; the console shows "Refused to execute inline script" or "Refused to apply inline style" | A proxy `Content-Security-Policy` whose `script-src` or `style-src` lacks `'unsafe-inline'`, or lists a nonce or hash, reaches the report frame. Start from the sample policy in section 6, "Content-Security-Policy": the end-to-end tests run behind it. |

## 12. Uninstall

```sh
docker compose down -v
docker image rm corelata/app:<version> postgres:16-alpine
```

`down -v` deletes the volumes: **all data is gone**, so take a backup first if you may want it.
Then remove the bundle directory. To stop the stack and keep the data, use `docker compose down`
without `-v`. If you ran the demo, remove it too:
`docker compose -f compose.yaml -f compose.demo.yaml down -v` (the project `corelata-demo`).

## 13. What is inside

- **The app image** (`corelata/app:<version>`) holds the API with the built web app, the worker,
  the `corelata` command-line tool and the synthetic model server of the demo. It runs as uid:gid
  10001:10001, with the configuration read-only at `/etc/corelata`, the files volume at
  `/data/files`, the web app at `/opt/corelata/web` and the example sources at
  `/opt/corelata/examples`. The same image runs `migrate`, `worker` and `api`; only the command
  differs. It also carries Tesseract and the language packs it was built with, for scanned PDFs
  (section 5, "Scanned PDFs").
- **The database image** is the official `postgres:16-alpine`, unchanged.
- **`sbom/`** holds a software bill of materials in CycloneDX JSON for the app image
  (`app.cdx.json`), the database image (`postgres.cdx.json`) and the web app's dependencies
  (`web.cdx.json`).
- **`manifest.json`** records the bundle's `version`, the source `commit`, the `platform`, when it
  was built, the id and tag of each image, the digest the database image was pulled by
  (`postgres_image`), and the `packs` it carries.
- **Versions.** `VERSION`, the image's `org.opencontainers.image.version` label
  (`docker image inspect corelata/app:<version>`), `manifest.json`, `GET /api/health`, the foot of
  the web app's sidebar, Settings ▸ Technical details and `corelata --version` all carry the bundle's version. The Python package
  inside has its own version (`corelata --version` prints both when they differ).

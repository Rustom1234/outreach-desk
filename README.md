# The Outreach Desk

A configurable, multi-stage cold-outreach pipeline. It researches a target,
writes a personalized message, filters that message for generic AI-slop
phrasing, and hands the result to a delivery backend -- all driven by a
small YAML config instead of hardcoded logic.

> **All data in this repo is synthetic.** The example targets, the example
> sender persona, and every email address (`@example.com` / `@example.org`)
> are fictional. No real person, institution, or company appears anywhere
> in this repository.

## What it solves

Cold outreach at any scale has two failure modes: it's either generic
(same template to everyone, ignored) or it takes so long per message that
scale isn't possible. This pipeline does the personalization research work
automatically, then runs every draft through a quality filter before it
ever reaches an inbox:

- A static filter strips or blocks a curated list of AI-slop and
  corporate-speak phrases ("delve", "leverage", "at the intersection of",
  "cutting-edge", ...). See `data/banned_phrases.csv`.
- A model-based fact-checker catches a more subtle failure: the drafting
  model inventing an affiliation for the recipient that isn't true (e.g.
  claiming a professor co-founded a company they have no connection to).
- Both checks retry the draft rather than silently letting a bad one
  through.

The goal is that a personalized message reads like it was actually written
by a person who did the reading, not generated from a mail-merge template.

## Architecture: four discrete stages

The pipeline is organized as four stages, each an importable module with a
single clear entry function, so each stage can be run, tested, or watched
independently:

```
Front Desk  ->  Scout  ->  Drafter  ->  Outbox
(intake)       (research)  (write + QA)  (deliver)
```

| Stage | Module | Responsibility |
|---|---|---|
| **Front Desk** | `outreach_desk/stages/front_desk.py` | Loads the sender's profile, resolves the target-type config, loads the target list. The one stage that "takes input" -- your profile/resume and target list live here. |
| **Scout** | `outreach_desk/stages/scout.py` | For each target: scrapes configured context pages for research signals, then resolves a contact email through a waterfall (`known_email` -> scrape `context_urls` -> web search -> Hunter.io). Every external call degrades gracefully if a key or page is missing. |
| **Drafter** | `outreach_desk/stages/drafter.py` | One Claude call per target writes a personalized paragraph, which is then run through the banned-phrase filter and an affiliation fact-checker, retrying on failure. Assembles the final email from the target-type's greeting/outro templates. |
| **Outbox** | `outreach_desk/stages/outbox.py` | Delivery. Default backend writes one `.txt`/`.json` file per draft to `outbox/` and never sends anything. An optional Gmail backend creates Gmail **drafts** (never sends), gated behind config and your own OAuth credentials. |

Because each stage is a plain function (`front_desk.intake`, `scout.run`,
`drafter.run`, `outbox.run`) taking and returning plain data, the pipeline
is straightforward to visualize as discrete steps -- see the optional
pixel-agents section below.

### The target abstraction

A "target" is generic: `{name, role, org, context_urls, notes, known_email}`.
It doesn't matter whether the target is a professor, a recruiter, or a
potential client -- the schema is the same. What changes per run is the
**target type**, selected with `--target-type {academic,recruiter,client}`,
which controls:

- tone and subject-line style
- the greeting/outro templates
- the framing rules injected into the drafting prompt
- which context signals the Scout stage looks for on a target's pages
  (e.g. "publications" for academic targets, "open roles" for recruiters,
  "product launch" for clients)

The academic case (the original single-purpose version of this tool) is
now just one config among three -- see `configs/academic.yaml`.

## Configuring a target type

Each target type is a YAML file in `configs/`:

```yaml
# configs/academic.yaml
target_type: academic
tone: "warm, peer-curious, intellectually honest about gaps in background"
subject_style:
  prefix: "Research interest in"
greeting_template: "Hi {first},"
outro_template: |
  I'd genuinely love a short conversation...
  {sender_name}
context_signals:
  - publications
  - research group
  - postdoc
draft_instructions: |
  - Lead with what the sender actually works on...
```

Swap `--target-type academic` for `--target-type recruiter` or
`--target-type client` to change tone, templates, and research focus
without touching any code. Add a new target type by dropping in a new YAML
file and adding its name to the `--target-type` choices in
`outreach_desk/pipeline.py`.

The sender's own identity (name, bio, affiliations) is a separate config,
`configs/sender.example.yaml` -- copy it and edit in your own details; it's
never hardcoded into the pipeline logic.

## Running the demo

```bash
pip install -r requirements.txt
python -m outreach_desk.pipeline --target-type academic --limit 3 --dry-run
```

or:

```bash
bash examples/run_demo.sh
```

`--dry-run` runs Front Desk and Scout only (loads config/targets, attempts
to resolve emails) and skips the Drafter and Outbox stages, so **it works
with zero API keys configured**. Drop `--dry-run` to also generate and
save personalized drafts, which requires `ANTHROPIC_API_KEY` (copy
`.env.example` to `.env` and fill it in). `HUNTER_API_KEY` is optional and
only used as the last resort in the Scout waterfall.

By default, generated drafts are written to `outbox/` as one `.txt` and
one `.json` file per target -- nothing is ever sent automatically. To
enable the optional Gmail-drafts backend, set `delivery.backend: gmail` in
a target-type config and provide your own `credentials.json` /
`token.json` (both gitignored, not included here); it still only creates
Gmail drafts, never sends.

## Optional: watch the stages run with pixel-agents (nice-to-have)

Because each stage is a discrete function with clear boundaries, it maps
well onto the open-source [pixel-agents](https://github.com/) visualizer,
which renders a coding agent's transcript as pixel-art office characters
moving between "desks." To try it locally against this project's own
Claude transcripts:

1. Run pixel-agents locally, pointed at `~/.claude/projects` for this
   repo's session transcripts.
2. Bind it to loopback only: `127.0.0.1:3100`.
3. Port note: if you also run `claudecodeui` locally, that tends to use
   `3456` -- keep pixel-agents on `3100` to avoid a collision.

This is purely a local dev-time visualization and not part of the
pipeline itself; no hosting or deployment is set up or implied.

## Repository layout

```
outreach_desk/
  config.py          # loads target-type + sender YAML
  quality.py          # banned-phrase filter (reusable standalone)
  constants.py         # model IDs, retry budget
  pipeline.py          # orchestrator + CLI
  stages/
    front_desk.py
    scout.py
    drafter.py
    outbox.py
configs/
  academic.yaml
  recruiter.yaml
  client.yaml
  sender.example.yaml
data/
  targets.example.json  # synthetic demo targets
  banned_phrases.csv
examples/
  run_demo.sh
```

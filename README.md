# crosscheck-loop

A multi-model build loop with an adversarial audit and a hard stop condition.

One model is too easy on itself. crosscheck splits a build across model families so the
builder is never its own judge, then refuses to call the job done until the critics have
actually signed off on the exact file you are about to ship. It is a method first and a
reference script second: the loop design below is model-agnostic, and `glm_fanout.py` is
just one cheap way to run the drafting step.

## What it's for

Any build where being wrong is expensive and one model's self-review is not enough:

- A document or deck that has to be correct (a proposal, a report, an RFP response).
- A code change where a regression in the untouched parts would slip past a prose review.
- A data-heavy artifact where numbers have to reconcile and sources have to hold up.

If the task is a quick one-liner, skip it. The team is overhead until the build is big
enough to earn it.

## Do you have to use specific models?

No. The only hard rule is **cross-family**: the critics must be a different model family
than the builder, because a same-family critic shares the builder's blind spots. Which
vendors you use is entirely up to whatever API keys you already have. The structure is the
value, not the brand of model in each seat.

## The loop

1. **Draft (worker, fanned out).** A fast, cheap model drafts N variants in parallel from
   one shared brief. On a *modification* (editing a locked file) it delta-drafts only the
   changed region instead of N full rewrites. The drafter never judges and never ships.
2. **Optional data deputy (worker).** On figure-heavy builds, a second worker pulls
   sources, builds the number tables, and populates the requirement ledger. Hard boundary:
   **it populates, it never signs off.** A worker never verifies its own data pull, so the
   adversarial critics still run on everything it filled. Its "do not use X" caveats fold
   into the brief as binding build constraints, not just ledger rows, so the builder is
   bound before the build, not only caught at audit.
3. **Adversarial critics, cross-family.** At least two critics on a *different model family*
   than the builder, told to break the work, not bless it. Cross-family matters: a critic
   from the same family as the builder shares its blind spots. On code-bearing builds, give
   one critic a render/technical lens (it catches the regression class prose critics miss,
   e.g. a CSS bar fill computing to 0px).
4. **Lead judges and loops to convergence.** The lead applies the real findings and
   re-submits. **The loop is not done until both critics approve the same unchanged final.**
   Any edit after a clean pass voids that pass, so the file you ship is one the critics
   actually saw, not one edited past their last look.
5. **Requirement ledger.** One row per must-have, each marked proved / weak / missing /
   contradicted before ship. This catches the gap critics cannot see: the must-have nobody
   put on the page. On for correctness-critical builds (RFPs, anything with a spec).
6. **Honesty guard.** A run that hit its round cap, stalled in a two-round stalemate, or
   errored out is reported as exactly that. It is never relabelled "approved."
7. **Gate trivial work back to solo.** If the task is a one-liner, the team is overhead.
   Run the loop only when the build is big enough to earn it.

## Why it works

Adversarial + different model family + loop-to-clean is about 80 percent of the lift. The
cheap parallel drafting is an accelerant, not the value. The stop condition (convergence +
ledger + honesty guard) is what keeps a plausible-but-wrong artifact from shipping.

## Setup: what you need

Three seats. Fill each with any model you have access to, as long as the critics are a
different family than the builder.

| Seat | What it does | Fill it with (examples) | How you call it |
|---|---|---|---|
| **Drafter** | Writes the variants / the change | GLM, Llama, a cheap fast model | `glm_fanout.py` (any OpenAI-compatible API) |
| **Critic 1** | Adversarial review, technical/render lens | a CLI coding agent (Codex, Claude Code, etc.) | its own CLI, on the copied artifact |
| **Critic 2** | Adversarial review, fresh eyes | a third family (Gemini, Claude, GPT, ...) | API call or a subagent |
| **Lead (you)** | Judges, applies findings, enforces the stop | any capable model, or you by hand | runs the loop |

Minimum to start: **one API key for the drafter** plus **two critics on a different family
than the drafter**. The critics can be two CLI tools you already have logged in (no extra
keys), or two more API keys. A worked example:

- Drafter: GLM via Ollama Cloud (`CROSSCHECK_API_KEY`)
- Critic 1: a `codex`-style CLI you are already signed into (GPT family)
- Critic 2: a Claude or Gemini subagent (a third family)
- Lead: you, or whichever assistant you are already chatting with

That spans three families, so no critic shares the drafter's blind spots. Swap any seat for
what you have. If you only have two families total, run one critic per family and you still
get the cross-family catch.

## glm_fanout.py

A reference implementation of step 1: parallel draft fan-out against any
OpenAI-compatible chat endpoint.

```sh
export CROSSCHECK_API_KEY=...            # your provider key
# optional: export CROSSCHECK_API_URL=https://your-endpoint/v1/chat/completions
python3 glm_fanout.py examples/job.example.json
```

`job.json`: `system`, `user`, `angles` (one variant per key), `out_prefix`, optional
`model`, `max_tokens`, `temperature`, `ext` (`md` or `html`). Auth and endpoint come from
the environment (see `.env.example`). Each angle runs in its own thread, so N variants
return concurrently. Run it as a background job.

The default endpoint targets [Ollama Cloud](https://ollama.com) with `glm-5.2`, chosen for
being near-free, long-context, and a third model family distinct from GPT and Claude (so it
makes a good cross-family worker). Any OpenAI-compatible provider and model works: set
`CROSSCHECK_API_URL` and the `model` field.

## Critics (reference setup)

The loop needs at least two adversarial critics on a different family than the builder. One
proven setup:

- A CLI coding agent (e.g. an OpenAI-family `codex exec`-style tool) as the technical critic.
  Copy the artifact's **whole folder** (HTML plus `assets/` and any locally referenced dirs)
  into a temp dir before review: a temp dir so it cannot touch the real file, the whole folder
  so local assets resolve on headless render (copying only the HTML false-flags images as
  missing).
- A fresh-eyes subagent on a third family, told to find what is wrong and return numbered
  findings with verbatim lines and fixes.

Swap in whatever critics you have, as long as they are adversarial and cross-family.

## Config surface

`variants`, `modificationMode` (delta-draft the change, then regression-audit the whole
file), `dataDeputy` (optional worker that populates the ledger but never signs off),
`criticModels` (at least two, cross-family), `requireConvergence` (both critics approve the
same unchanged final), `requirementLedger` (on for correctness-critical builds), `stopOn`
(clean pass, two-round stalemate, or cap, never an errored run reported as clean),
`maxAuditRounds`, `mode` (`light` is one audit pass, `deep` loops to clean).

## Status

Method, with two case validations and the tuning notes from each. This is the generalized
core; it is run in production behind domain-specific gates that are not published here.
Issues and PRs against the **loop design** are welcome (see CONTRIBUTING). It is not a
50-run-hardened framework, and the tuning notes are the most useful part: they are the
non-obvious failure modes you would otherwise hit yourself.

## License

MIT. See LICENSE.

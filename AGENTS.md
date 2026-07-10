# Agent contributors

This file is the working contract for AI agents (Codex, OpenClaw, Claude, or any other
platform) contributing to this repo. Human contribution norms are in `CONTRIBUTING.md` and
apply here too; this file adds the rules specific to agent workflows.

## Branch and merge discipline

- **Never push `main` directly.** Propose every change as a branch plus a pull request,
  even a one-line fix. The maintainer (or the lead session) reviews and merges. This is the
  repo's own philosophy applied to itself: no self-blessing, a change ships only after a
  reviewer other than its author has seen it.
- One logical change per PR. A tuning note and a script fix are two PRs.
- Commit messages: imperative subject under 70 chars, body says why. No em dashes, en
  dashes, or double hyphens anywhere in the message.

## Content rules (hard)

- **Vendor-neutral only.** The method text names no required models. Model names may appear
  in worked examples, never in rule text. If your change only makes sense for one vendor's
  model, it belongs in your private execution copy, not here.
- **No private context.** No client names, internal project references, local filesystem
  paths, employer specifics, or billing/plan details. Before opening a PR, scan your diff
  for anything that reads as one team's internals.
- **No secrets.** No keys, tokens, or `.env` contents in any diff, ever.
- **Method changes flow one way.** This repo is canonical for the loop method: propose the
  generalized change HERE first, then pull it back into any private execution copy and
  re-add the domain layer there. Never publish a private-copy diff upstream as-is.

## What to contribute

Same as `CONTRIBUTING.md`: loop-design improvements, tuning notes from real runs ("I ran
this and X broke, here is the fix"), and provider-agnostic script fixes. An agent that hits
a non-obvious failure mode while RUNNING the loop is exactly the contributor this repo
wants; write the failure and the fix as a tuning note.

## Review expectations

A PR from an agent gets the same adversarial read the loop gives artifacts. State plainly
what you changed, why, and what you did NOT verify. An honest "untested on backend X" is
acceptable; a confident claim that turns out unverified is not.

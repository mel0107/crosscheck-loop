# Contributing

This repo is a **method plus a reference implementation**, not a framework that locks you
into specific model vendors.

## What good contributions look like

- **Loop-design improvements.** A sharper stop condition, a failure mode the current loop
  misses, a better way to surface a missing requirement. These are the valuable ones.
- **Tuning notes from a real run.** "I ran this and X broke, here is the fix" is exactly
  the kind of non-obvious failure mode this repo exists to collect.
- **Provider-agnostic fixes** to `glm_fanout.py` (it already takes endpoint and key from
  the environment; keep it that way).

## What will be declined

- PRs that hardcode a specific vendor, model, or local path.
- "Use my preferred model instead of yours." Model choice is a config decision, not a
  method change. The loop is family-agnostic on purpose.
- Secrets, keys, or `.env` files in the diff.

## Sync note (for the maintainer)

The public repo is canonical for the **loop method**. Method changes originate here and are
pulled back into any private execution copy, never the reverse. Domain-specific gates live
in the private copy and are not published.

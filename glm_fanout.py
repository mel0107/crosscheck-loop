#!/usr/bin/env python3
"""Parallel draft fan-out for the crosscheck loop (OpenAI-compatible chat API).

Usage:  python3 glm_fanout.py <job.json>

job.json schema:
{
  "system":     "<system prompt / voice contract>",
  "user":       "<the shared brief + locked data>",
  "angles":     {"A-plain": "ANGLE: ...", "B-analyst": "ANGLE: ...", ...},  # one variant per key
  "out_prefix": "/abs/path/draft",            # writes <prefix>-<angle>.<ext>
  "model":      "glm-5.2",    # optional
  "max_tokens": 4000,          # optional
  "temperature": 0.6,          # optional
  "ext":        "md"           # optional, "md" or "html"; if "html", strips a ```html ... ``` fence
}

Auth and endpoint come from the environment so this stays provider-agnostic:
  CROSSCHECK_API_KEY   the bearer token (required)
  CROSSCHECK_API_URL   chat-completions endpoint (default: https://ollama.com/v1/chat/completions)
  CROSSCHECK_ENV_FILE  optional path to a .env file holding the two vars above
                     (handy when the shell rc is not sourced, e.g. inside a tool runner)

Each angle runs in its own thread, so N variants come back concurrently.
"""
import json, os, sys, re, pathlib, threading, urllib.request

DEFAULT_URL = "https://ollama.com/v1/chat/completions"


def load_env_file(path):
    """Populate os.environ from a simple KEY=value .env file (does not override existing)."""
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


def load_key():
    env_file = os.environ.get("CROSSCHECK_ENV_FILE")
    if env_file:
        load_env_file(env_file)
    key = os.environ.get("CROSSCHECK_API_KEY")
    if not key:
        raise SystemExit(
            "CROSSCHECK_API_KEY not set. Export it, or point CROSSCHECK_ENV_FILE at a .env "
            "file containing it (see .env.example)."
        )
    return key


def gen(key, url, job, aid, angle):
    body = json.dumps({
        "model": job.get("model", "glm-5.2"),
        "messages": [
            {"role": "system", "content": job["system"]},
            {"role": "user", "content": job["user"] + "\n\n" + angle},
        ],
        "temperature": job.get("temperature", 0.6),
        "max_tokens": job.get("max_tokens", 4000),
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=600))
        txt = resp["choices"][0]["message"]["content"]
        if job.get("ext") == "html":
            m = re.search(r"```(?:html)?\s*(.*?)```", txt, re.S)
            txt = m.group(1).strip() if m else txt.strip()
        ext = job.get("ext", "md")
        out = f'{job["out_prefix"]}-{aid}.{ext}'
        pathlib.Path(out).write_text(txt)
        u = resp.get("usage", {})
        print(f"OK {aid}: {len(txt)} chars, tokens={u.get('total_tokens', '?')} -> {out}")
    except Exception as e:
        print(f"FAIL {aid}: {e}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 glm_fanout.py <job.json>")
    job = json.load(open(sys.argv[1]))
    key = load_key()
    url = os.environ.get("CROSSCHECK_API_URL", DEFAULT_URL)
    threads = [threading.Thread(target=gen, args=(key, url, job, a, v)) for a, v in job["angles"].items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("ALL DONE")


if __name__ == "__main__":
    main()

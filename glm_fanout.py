#!/usr/bin/env python3
"""crosscheck-loop parallel fan-out: N drafts or N critic calls against a hosted model endpoint.

Usage:  python3 glm_fanout.py <job.json>

job.json schema:
{
  "system":      "<system prompt / voice contract>",
  "user":        "<the shared brief + locked data>",
  "angles":      {"A-plain": "ANGLE: ...", "B-analyst": "ANGLE: ..."},  # one variant per key
  "out_prefix":  "/abs/path/draft",       # writes <prefix>-<angle>.<ext>
  "model":       "glm-5.3-flash",         # optional; any id your endpoint serves
  "models":      ["glm-5.3-flash", "deepseek-v4-pro"],  # optional; several models in ONE process so the
                                          # concurrency cap holds across all of them (output gets -<model> suffix)
  "num_predict": 100000,                  # optional output budget; thinking counts against it
  "think":       true,                    # optional; false = no reasoning pass (faster, weaker)
  "temperature": 0.3,                     # optional
  "concurrency": 3,                       # optional; requests in flight at once
  "retries":     4,                       # optional
  "timeout":     1800,                    # optional, seconds per request
  "save_thinking": false,                 # optional; also write <prefix>-<angle>.thinking.txt
  "ext":         "md",                    # optional, "md" or "html"; html strips a ```html fence
  "endpoint":    "https://openrouter.ai/api/v1/chat/completions",  # optional, OpenAI-compatible path
  "key_env":     "OTHER_PROVIDER_KEY"     # optional env var name, default CROSSCHECK_API_KEY
}

Observed behaviour on Ollama Cloud (the model names below are examples of what was run):
- Payload size is not the problem. 51 KB of report copy and 40 KB of Python
  both answer in 1 to 25 s on glm-5.3, glm-5.3-flash and deepseek-v4-pro.
- Ollama Cloud rate-limits concurrent requests. Past the limit it returns HTTP
  429 at once, or queues the request and then closes the socket at 60 s with
  "Remote end closed connection without response" and zero bytes received.
  Fix: a concurrency cap (default 3) plus retry with backoff on 429 and on a
  zero-byte disconnect.
- Thinking shares the output budget. A critic pass thinks for 150 to 250 K
  characters; with num_predict 40000 the run ends done_reason=length with
  EMPTY content. glm-5.3 also sometimes puts the whole answer in the thinking
  field and stops with empty content. Fix: default num_predict 100000, and
  any empty-content run with thinking present is rerun with think=false (the
  thinking is kept in <prefix>-<angle>.thinking.txt).
- deepseek-v4-pro caps output at 65536 tokens and returns HTTP 400 for a
  larger num_predict (it presents as "400 Bad Request in 1 s"). The script reads the cap out of the error and retries with it.
- The concurrency cap only holds inside one process. Running three fan-out
  processes at once put nine requests in flight and the 60 s disconnects came
  back. Put every model in one job via "models".
- Streaming is required: a non-streamed request sits silent through the whole
  generation and the same 60 s reaper closes it.
- The native /api/chat endpoint is used for Ollama (it exposes think and
  num_predict). The OpenAI-compatible /v1 path is kept only for the
  endpoint/key_env override (any OpenAI-compatible provider).

Auth: CROSSCHECK_API_KEY in the environment, or CROSSCHECK_ENV_FILE pointing at a KEY=value
.env file (agent hosts run non-login shells, so exported profile vars are often absent).
"""
import json
import pathlib
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request

import os

OLLAMA_CHAT = os.environ.get("CROSSCHECK_CHAT_URL", "https://ollama.com/api/chat")


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


def load_key(key_env="CROSSCHECK_API_KEY"):
    env_file = os.environ.get("CROSSCHECK_ENV_FILE")
    if env_file:
        load_env_file(env_file)
    key = os.environ.get(key_env)
    if not key:
        raise SystemExit(
            key_env + " not set. Export it, or point CROSSCHECK_ENV_FILE at a .env "
            "file containing it (see .env.example)."
        )
    return key


def _request(url, key, payload, timeout):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def _stream_ollama(key, payload, timeout):
    """Native /api/chat stream. Returns (content, thinking, done_reason, bytes_seen)."""
    content, thinking, reason, seen = [], [], None, 0
    with _request(OLLAMA_CHAT, key, payload, timeout) as resp:
        for raw in resp:
            seen += len(raw)
            try:
                d = json.loads(raw)
            except Exception:
                continue
            if d.get("error"):
                raise RuntimeError(d["error"])
            m = d.get("message", {})
            if m.get("content"):
                content.append(m["content"])
            if m.get("thinking"):
                thinking.append(m["thinking"])
            if d.get("done"):
                reason = d.get("done_reason")
                break
    return "".join(content), "".join(thinking), reason, seen


def _stream_openai(url, key, payload, timeout):
    """OpenAI-compatible SSE stream. Returns (content, reasoning, finish_reason, bytes_seen)."""
    content, reasoning, finish, seen = [], [], None, 0
    with _request(url, key, payload, timeout) as resp:
        for raw in resp:
            seen += len(raw)
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                ch = json.loads(data)["choices"][0]
            except Exception:
                continue
            delta = ch.get("delta", {})
            if delta.get("content"):
                content.append(delta["content"])
            if delta.get("reasoning"):
                reasoning.append(delta["reasoning"])
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    return "".join(content), "".join(reasoning), finish, seen


def _build(job, angle, think):
    messages = [
        {"role": "system", "content": job["system"]},
        {"role": "user", "content": job["user"] + "\n\n" + angle},
    ]
    model = job.get("model", "glm-5.3-flash")
    temp = job.get("temperature", 0.3)
    if job.get("endpoint"):
        p = {"model": model, "messages": messages, "temperature": temp,
             "max_tokens": job.get("num_predict", job.get("max_tokens", 100000)), "stream": True}
        effort = job.get("reasoning_effort")
        if effort:
            p["reasoning_effort"] = effort
        return p
    return {"model": model, "messages": messages, "think": think, "stream": True,
            "options": {"num_predict": job.get("num_predict", job.get("max_tokens", 100000)),
                        "temperature": temp}}


def gen(key, job, aid, angle, sem, log):
    attempts = job.get("retries", 4)
    timeout = job.get("timeout", 1800)
    think = job.get("think", True)
    endpoint = job.get("endpoint")
    content = thinking = ""
    reason = err = None
    t0 = time.time()
    for attempt in range(1, attempts + 1):
        payload = _build(job, angle, think)
        try:
            with sem:
                if endpoint:
                    content, thinking, reason, seen = _stream_openai(endpoint, key, payload, timeout)
                else:
                    content, thinking, reason, seen = _stream_ollama(key, payload, timeout)
            if content.strip():
                break
            if think and thinking.strip():
                # Some thinking models write the whole answer into the thinking
                # field and stop with empty content, or thinking eats the budget
                # (done=length). Both:
                # keep the thinking on disk and rerun the angle with think off.
                err = f"empty content, done_reason={reason}, thinking {len(thinking)} chars"
                pathlib.Path(f'{job["out_prefix"]}-{aid}.thinking.txt').write_text(thinking)
                think = False
                log(f"  retry {aid}: attempt {attempt} {err}; retrying with think=false")
                continue
            err = f"empty content, done_reason={reason}, bytes={seen}"
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code == 429:
                pause = 10 * attempt + random.uniform(0, 5)
                log(f"  retry {aid}: attempt {attempt} rate limited, sleeping {pause:.0f}s")
                time.sleep(pause)
                continue
            if e.code == 400:
                try:
                    err += " " + e.read().decode("utf-8", "ignore")[:200]
                except Exception:
                    pass
                m = re.search(r"maximum output tokens \((\d+)\)", err)
                if m:
                    # deepseek-v4-pro caps num_predict at 65536; clamp and retry at once
                    job = dict(job, num_predict=int(m.group(1)))
                    log(f"  retry {aid}: attempt {attempt} budget above model cap, clamping num_predict to {m.group(1)}")
                    continue
            if e.code >= 500:
                pause = 5 * attempt + random.uniform(0, 5)
                log(f"  retry {aid}: attempt {attempt} {err}; sleeping {pause:.0f}s")
                time.sleep(pause)
                continue
            # any other 4xx is a request the server will not accept on retry
            log(f"  stop {aid}: {err}")
            break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if "closed connection" in str(e) or "timed out" in str(e).lower():
                pause = 5 * attempt + random.uniform(0, 5)
                log(f"  retry {aid}: attempt {attempt} {err}; sleeping {pause:.0f}s")
                time.sleep(pause)
                continue
        if attempt < attempts:
            log(f"  retry {aid}: attempt {attempt} failed ({err})")

    secs = int(time.time() - t0)
    txt = content
    if not txt.strip():
        log(f"FAIL {aid}: {err} (after {attempts} attempts, {secs}s)")
        return
    if job.get("ext") == "html":
        m = re.search(r"```(?:html)?\s*(.*?)```", txt, re.S)
        txt = m.group(1).strip() if m else txt.strip()
    ext = job.get("ext", "md")
    out = f'{job["out_prefix"]}-{aid}.{ext}'
    pathlib.Path(out).write_text(txt)
    if job.get("save_thinking") and thinking:
        pathlib.Path(f'{job["out_prefix"]}-{aid}.thinking.txt').write_text(thinking)
    log(f"OK {aid}: {len(txt)} chars, thinking {len(thinking)} chars, done={reason}, "
        f"think={'on' if think else 'off'}, {secs}s -> {out}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 glm_fanout.py <job.json>")
    job = json.load(open(sys.argv[1]))
    key = load_key(job.get("key_env", "CROSSCHECK_API_KEY"))
    sem = threading.Semaphore(job.get("concurrency", 3))
    lock = threading.Lock()

    def log(msg):
        with lock:
            print(msg, flush=True)

    models = job.get("models") or [job.get("model", "glm-5.3-flash")]
    threads = []
    for model in models:
        mjob = dict(job, model=model)
        if len(models) > 1:
            mjob["out_prefix"] = f'{job["out_prefix"]}-{model.split(":")[0]}'
        threads += [threading.Thread(target=gen, args=(key, mjob, a, v, sem, log))
                    for a, v in job["angles"].items()]
    for t in threads:
        t.start()
        time.sleep(1)  # stagger so one burst does not trip the rate limit
    for t in threads:
        t.join()
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()

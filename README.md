# Adaptive Self-Healing Engineer

A closed-loop QA system that finds bugs the way real users do, then fixes them
autonomously with Codex. A swarm of AI personas explores a live web app in
parallel browsers, flags what feels wrong, a verifier filters out
hallucinations and duplicates, and Codex diagnoses, patches, and tests the
verified bugs without a human in the loop. A persona then re-runs against the
patched site to confirm the fix held.

---

## Table of contents

1. [What this is](#what-this-is)
2. [Why it is different](#why-it-is-different)
3. [How it works](#how-it-works)
4. [Repository layout](#repository-layout)
5. [Prerequisites](#prerequisites)
6. [Setup from scratch (teammates start here)](#setup-from-scratch)
7. [Running it](#running-it)
8. [The dashboard](#the-dashboard)
9. [Configuration and flags](#configuration-and-flags)
10. [How to extend it](#how-to-extend-it)
11. [Troubleshooting](#troubleshooting)

---

## What this is

Most QA tooling falls into one of two camps. Persona testing tools deploy
simulated users that explore a product and file bug reports, but a human still
has to fix everything. Autonomous coding agents can fix a bug once a human
hands them a clear description, but they cannot decide what is worth fixing on
their own. This project closes the loop between the two.

The system runs against a deliberately buggy e-commerce prototype (a
Shopee-style "team up with a friend for a group discount" site). It is built so
the whole cycle, from discovery to a promoted fix, and runs with no human intervention.

The current build ships three personas. The architecture
is designed to scale to as many user archetypes as a real product needs.

---

## Why it is different

There are three kinds of tools in this space today, and none of them close the
loop:

- Persona QA tools find bugs and file tickets. A human fixes them.
- Autonomous coding agents fix bugs but need a human to find and describe them.
- Conversational persona platforms have personas that chat to give product
  managers qualitative feedback. The output is a transcript, not a fix.

In this system the personas do not chat. They drive real browsers and look at
the rendered page through a vision model the way a human user would. The output
is not a ticket or a transcript. It is a passing test and a promoted patch.

---

## How it works

The pipeline runs in five stages. Each stage solves a problem the others
cannot.

```
Stage 0  Reset            Restore the prototype to its known-buggy baseline.

Stage 1  Discovery        Three personas explore the site in parallel browsers.
                          One runs headed (visible), two run headless. Each
                          persona has a distinct archetype and goal. They look
                          at screenshots, click and type, narrate their
                          reasoning, and file structured bug reports.

Stage 2  Verifier triage  A verifier model reads each report against the actual
                          source code and classifies it as real, a
                          misunderstanding, or a duplicate. Only verified-real
                          bugs advance. This gate is what prevents Codex from
                          producing confident phantom fixes for bugs that were
                          never real.

Stage 3  Codex heal       For each verified bug, Codex (gpt-5-codex via the
                          Responses API) reads the relevant files, writes a
                          patch in an isolated sandbox, runs the specific
                          failing test, and promotes the fix to the live tree
                          once the test passes.

Stage 4  Re-validation    A persona re-runs against the patched site. Its
                          reports go through the verifier again so that rounding
                          noise is not mistaken for a real regression.

Stage 5  Scoreboard       Bugs found, bugs healed, regressions, wall time. The
                          dashboard replays the entire run from a saved
                          transcript.
```

The three personas in the current build:

- Priya, a deal hunter who tries promo codes and checks whether the discount
  actually applied.
- Kelvin, a price-sensitive shopper who scrutinizes the savings math on the
  team purchase page.
- Hassan, a comparison shopper who notices when a price differs between the
  homepage and the product detail page.

See `prototype/BUGS.md` for the full catalogue of planted bugs. That file is
the private answer key. It is for the team only and should never be made
public.

---

## Repository layout

```
.
├── prototype/                 The buggy e-commerce app under test
│   ├── main.py                FastAPI backend (the live, mutable target)
│   ├── main.py.buggy          Frozen baseline. Stage 0 restores from this.
│   ├── seed.py                Seeds the SQLite DB with sample products
│   ├── static/                Vanilla JS single-page frontend
│   ├── tests/                 Regression tests (describe correct behaviour)
│   └── BUGS.md                Private answer key for the planted bugs
│
├── personas/                  The AI shopper swarm
│   ├── persona_profiles.py    Persona definitions, goals, model routing
│   ├── run_one.py             Browser-driving loop (sync and async)
│   ├── llm_client.py          Gemini and OpenAI adapters
│   └── reports/               Generated transcripts (gitignored)
│
├── orchestrator/              The healing engine
│   ├── full_loop.py           End-to-end runner (the main entry point)
│   ├── agent.py               Codex heal loop
│   ├── verifier.py            Pre-heal triage (real vs phantom vs duplicate)
│   ├── sandbox.py             Isolated copy-and-test sandbox
│   ├── tools.py               Codex tool schemas (read, write, list, test, done)
│   └── tests/                 Sandbox unit tests
│
├── dashboard/
│   └── index.html             Mission-control replay dashboard (single file)
│
├── team/                      Hackathon planning docs
├── architecture.png/.svg      Architecture diagram
├── requirements.txt           Consolidated dependencies
│
├── run_all.bat                Start server, then run the full loop
├── run_server.bat             Start only the server
├── run_loop.bat               Run only the loop (server must be up)
└── run_fancy_visuals.bat      Open the dashboard in a browser
```

---

## Prerequisites

Every teammate needs the following installed before starting:

- Python 3.10 or newer (the build was developed on 3.13). Check with
  `python --version`.
- Git.
- An OpenAI API key with access to the Codex and GPT-4o-mini models. This is
  required. Get one at https://platform.openai.com/api-keys.
- Optionally, a Google Gemini API key if you want personas to run on Gemini
  instead of OpenAI. The current personas are routed to OpenAI, so this is
  optional. Get one at https://aistudio.google.com/apikey.

---

## Setup from scratch

These are the exact steps for a teammate cloning the repo for the first time on
Windows. Mac and Linux differ only in the virtual-environment activation line,
noted below.

### 1. Clone the repository

```cmd
git clone https://github.com/wenlong96/<repo-name>.git
cd <repo-name>
```

You must be added as a collaborator first, because the repository is private.
Ask for an invite if you cannot see it.

### 2. Create and activate a virtual environment

Windows (Command Prompt):

```cmd
python -m venv .venv
.venv\Scripts\activate
```

Mac or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the start of your prompt once it is active.

### 3. Install Python dependencies

```cmd
pip install -r requirements.txt
```

### 4. Install the Playwright browser

The personas drive a real Chromium browser. Playwright needs to download it
once:

```cmd
playwright install chromium
```

### 5. Create your .env file

The project reads API keys from a `.env` file that is never committed. Copy the
example and fill in your keys:

Windows:

```cmd
copy personas\.env.example .env
```

Mac or Linux:

```bash
cp personas/.env.example .env
```

Then open `.env` and fill in at least your OpenAI key:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key (or leave blank, the 3 persona uses openai by default, but additional others will default to gemini for cheap calls)
GEMINI_MODEL=gemini-2.5-flash-lite
OPENAI_API_KEY=sk-your-real-openai-key
OPENAI_MODEL=gpt-4o-mini
```

Notes:

- The three personas are individually routed to OpenAI gpt-4o-mini in their
  profiles, so an OpenAI key is required even though `LLM_PROVIDER` defaults to
  gemini.
- The orchestrator and verifier always use OpenAI, so the OpenAI key is
  mandatory regardless.
- Place the `.env` at the repository root. The code loads it from there.

### 6. Seed the database

```cmd
cd prototype
python seed.py
cd ..
```

This creates `prototype/prototype.db` with the sample products. The database is
gitignored, so every teammate generates their own.

### 7. Verify the install

Run the regression tests on the prototype. You should see six failures and
three passes. The six failures are the planted bugs. This is expected and is
how you know the setup is correct.

```cmd
cd prototype
python -m pytest tests/ -q
cd ..
```

Then run the orchestrator sandbox tests, which should all pass:

```cmd
python -m pytest orchestrator/tests/ -q
```

If the prototype shows six failures and three passes, and the orchestrator
tests all pass, you are fully set up.

---

## Running it

There are convenience batch files in the repository root for Windows. On Mac or
Linux, run the equivalent commands shown below them.

### Option A: one click (recommended for a quick demo)

```cmd
run_all.bat
```

This opens the prototype server in its own window, waits until it is reachable,
then runs the full loop in the current window. When the loop finishes, the
server window stays open so you can run again.

### Option B: server and loop separately (recommended while developing)

Open two terminals. In the first:

```cmd
run_server.bat
```

Leave it running. The server uses auto-reload, so it picks up code changes
without a restart. In the second terminal:

```cmd
run_loop.bat
```

Run this as many times as you like. It is much faster than restarting the
server each time.

### Manual commands (Mac, Linux, or if you prefer no batch files)

Terminal 1, start the server:

```bash
cd prototype
python -m uvicorn main:app --reload --port 8000
```

Terminal 2, run the loop:

```bash
python -m orchestrator.full_loop
```

A successful run ends with a summary showing bugs found, bugs healed, and a
clean re-validation, and writes a transcript to `personas/reports/`.

---

## The dashboard (fancy visuals)

The dashboard replays a saved run as an animated, stage-by-stage visualization.
It is replay-first by design, so the live demo is never at the mercy of a rate
limit or a flaky network.

To open it:

```cmd
run_fancy_visuals.bat
```

Or open `dashboard/index.html` directly in any browser. Then click
"Choose file", select the most recent transcript from `personas/reports/`, and
press Play. The batch file prints the path to the newest transcript to save you
hunting for it.

Adjust playback speed with the 1x, 2x, 4x, 8x controls. Default is 2x.

---

## Configuration and flags (optional)

The full loop accepts several OPTIONAL flags. Pass them through the batch files too, for
example `run_loop.bat --sequential`.

- `--spotlight <persona>`   Which persona runs in the visible browser. Default
                            is priya.
- `--revalidator <persona>` Which persona runs the re-validation pass. Default
                            is kelvin.
- `--sequential`            Run personas one at a time instead of in parallel.
                            Slower but avoids rate limits entirely.
- `--stagger <seconds>`     Delay between parallel persona starts to avoid
                            per-minute token limits. Default is 15.
- `--all-headless`          Run every persona headless (no visible browser).
- `--max-steps <n>`         Maximum browser steps per persona. Default is 10.
- `--max-iterations <n>`    Maximum Codex tool calls per heal. Default is 12.
- `--no-revalidate`         Skip the re-validation stage.
- `--skip-reset`            Do not restore the buggy baseline first.

Persona-to-model routing lives in `personas/persona_profiles.py`. Each persona
can override the provider and model independently of the `.env` defaults.

---

## How to extend it

Adding a new persona: edit `personas/persona_profiles.py`, define a new
`Persona` with a clear goal, and add it to `ALL_PERSONAS`. Add its id to
`DISCOVERY_PERSONAS` in `orchestrator/full_loop.py` to include it in a run.

Adding a new planted bug: introduce the bug in `prototype/main.py` (or the
frontend), add a regression test in `prototype/tests/test_regressions.py` that
asserts the correct behaviour, document it in `prototype/BUGS.md`, then refresh
the baseline by copying `main.py` over `main.py.buggy`.

Tuning the verifier: the triage prompt and rules live in
`orchestrator/verifier.py`.

Tuning the heal loop: the Codex system prompt and iteration logic live in
`orchestrator/agent.py`.

---

## Troubleshooting

The loop says the server is not running.
Start the server first with `run_server.bat`, or use `run_all.bat` which starts
it for you. Confirm it is reachable at http://localhost:8000 in a browser.

Personas hit a rate limit (HTTP 429).
The three personas run in parallel and share your per-minute OpenAI token
budget. Increase the gap between starts with a larger `--stagger`, for example
`run_loop.bat --stagger 20`, or run `--sequential` to remove parallelism
entirely.

Playwright errors about a missing browser.
Run `playwright install chromium` again inside the activated virtual
environment.

A heal fails or hangs.
Each heal is capped at twelve Codex tool calls. If a specific bug fails to heal,
re-run the loop. The verifier names a target test for each bug to keep Codex
focused. Failures are usually transient.

The regression tests all pass when they should fail.
The prototype may already be patched from a previous run. Restore the baseline:
copy `prototype/main.py.buggy` over `prototype/main.py`, or just run the full
loop, which resets in Stage 0.

ModuleNotFoundError when running the loop.
Make sure the virtual environment is active (you should see `(.venv)` in your
prompt) and that you ran `pip install -r requirements.txt`.

Keys not picked up.
Confirm `.env` is at the repository root, not inside a subfolder, and that
there are no quotes around the key values.

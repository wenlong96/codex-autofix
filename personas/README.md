# Personas — Phase 2

One AI-driven persona that navigates the prototype like a human, finds
issues, and produces a structured report.

## Setup

### 1. Install dependencies

(In your project venv — activate it first.)

```bash
cd personas
pip install -r requirements.txt
playwright install chromium
```

The `playwright install chromium` step downloads the browser binary
(~150 MB). One-time, takes a minute.

### 2. Set up your API keys

```bash
copy .env.example .env       # Windows
# or
cp .env.example .env         # macOS/Linux
```

Open `.env` and paste your Gemini API key on the `GEMINI_API_KEY=` line.

Get a key at https://aistudio.google.com/apikey — make sure you're in
the project that has the paid credits.

### 3. Make sure the prototype is running

In another terminal:

```bash
cd prototype
python main.py
```

Server at http://localhost:8000.

## Run a persona

```bash
cd personas
python run_one.py --persona maria
```

You should see:
- A Chromium window pops up (headed mode)
- Console prints step-by-step what Maria is thinking and doing
- After ~20 steps or when she's "done", a structured report prints
- Full JSON report saved to `reports/maria_<timestamp>.json`

## Switching providers

To use OpenAI instead:

```
# in .env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

No code changes needed. One env var.

## Flags

```
--persona maria          # which persona (only 'maria' for now)
--target http://...      # target site URL
--headless               # run without showing browser window
--max-steps 20           # cap on actions before forcing "done"
```

## What to expect from a successful run

Maria should:
1. Land on the product list, browse
2. Click into a product (probably one in her price range)
3. See the team purchase option
4. Either start a team or buy solo
5. If she starts a team, she should notice that the "total savings" number
   looks off when only she's joined — that's bug #1 firing in her observation

In the report:
- `completed_purchase`: true/false depending on what she chose
- `friction_points`: things she found awkward
- `possible_bugs`: ideally includes something about the savings math being wrong

## Iteration tips

If she doesn't catch the bug, tweak `persona_profiles.py` to make her more
analytical or price-sensitive. Or adjust the system prompt in `run_one.py`
to remind her to scrutinize numbers.

If she gets stuck in a loop (keeps clicking the same thing), check:
- Is `page.get_by_text(...)` finding the right element?
- Are network calls finishing? (`wait_for_load_state("networkidle")`)

## File layout

```
personas/
├── llm_client.py          # Gemini/OpenAI abstraction
├── persona_profiles.py    # Maria's profile (more later)
├── run_one.py             # main runner
├── requirements.txt
├── .env.example
└── reports/               # JSON outputs from each run
```

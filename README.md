# RevShield AI

AI-powered revenue protection, recovery & intelligence tool for online
merchants — real ML risk scoring, a real RAG knowledge base, two
purpose-built AI agents backed by real Groq LLM calls, and a clean,
navbar-driven dashboard. Not a chatbot wrapper: the LLM only ever
explains and drafts language for facts that the ML models and rules
already computed.

## What's actually "real" here

| Piece | What it is |
|---|---|
| Risk scoring | `scikit-learn` IsolationForest fit fresh on each merchant's own transaction batch, blended with explainable business rules |
| Recovery scoring | Transparent weighted model today; auto-upgrades to a trained `LogisticRegression` once you've accumulated 25+ real offer outcomes (see `ml/recovery_model.py`) |
| RAG | `chromadb` persistent vector store, one collection per merchant, embedded locally (no extra API key). Every daily upload writes new grounded "fact" documents into it — that's the day-by-day "training" |
| LLM | Real Groq API calls (`llama-3.3-70b-versatile` by default) for every explanation, priority list, offer message, and chat answer — grounded in the ML/RAG facts, never given free rein to invent numbers |
| Agents | Two distinct agents with separate jobs and prompts — see below |
| Human-in-the-loop | Offers are `pending` → merchant `approve/reject/edit` → customer `accept/decline`. The AI never spends money or contacts a customer on its own |

## The two agents

**1. Analyst Agent** (`app/agents/analyst_agent.py`)
Revenue risk prediction, root-cause analysis, payment-state incident
detection ("debited but not confirmed"), transaction risk scoring, and
Revenue Autopsy. Runs automatically right after every data upload.

**2. Recovery Agent** (`app/agents/recovery_agent.py`)
Finds recovery candidates (abandoned carts, failed payments, inactive
high-value customers), ranks them under your recovery budget, drafts
offer messages, runs the what-if simulator, and powers the "Ask
RevShield" chat assistant.

Both agents call the *same* Groq client (`app/agents/groq_client.py`)
but with different system prompts and different grounding data — this
is what "assigning the right LLM per task" means in practice here: one
model, two disciplined roles.

## Project layout

```
revshield-ai/
  backend/            FastAPI app, SQLite DB, ML, RAG, both agents
    app/
      ml/              risk_model.py, recovery_model.py, forecasting.py
      rag/              vector_store.py, knowledge_builder.py
      agents/            analyst_agent.py, recovery_agent.py, groq_client.py
      routers/           auth, data, dashboard, risk, recovery, offers, assistant
    seed_demo_data.py    generates sample CSVs so you can try it immediately
    requirements.txt
    .env.example
    run.sh
  frontend/           Plain HTML/CSS/JS — no build step, one navbar, one page per section
    index.html
    styles.css
    app.js
```

## Running it

**Requirements:** Python 3.10+, a free [Groq API key](https://console.groq.com/keys).

```bash
cd backend
cp .env.example .env        # then open .env and paste your GROQ_API_KEY
./run.sh                    # creates a venv, installs deps, starts the API on :8000
```

(First run downloads a small local embedding model for Chroma — needs
internet once, then it's fully local.)

In a second terminal, try it with demo data:

```bash
cd backend
source .venv/bin/activate
python seed_demo_data.py    # writes backend/demo_data/{customers,transactions,orders}.csv
```

Then open `frontend/index.html` directly in your browser (or serve it,
e.g. `python -m http.server 5500` from the `frontend/` folder). Sign
up with any email, then in the **Data** tab upload, in order:
`customers.csv` → `transactions.csv` → `orders.csv`. Watch the
Dashboard, Risk & Incidents, and Recovery tabs populate from real model
output, and try the "Ask RevShield" chat.

If your frontend is served from a different origin than `localhost:8000`,
set `window.REVSHIELD_API_BASE` at the top of `frontend/app.js` (or in
a small inline `<script>` before it loads) to your backend's URL.

## Using it with your own data

CSV columns expected (extra columns are ignored):

- **customers.csv**: `customer_id, name, email, purchase_count, avg_order_value, total_spent, last_purchase_date`
- **transactions.csv**: `transaction_id, customer_id, amount, payment_method, channel, status, timestamp`
  — `status` ∈ `success | failed | pending | debited_not_confirmed | reversed | suspicious`
- **orders.csv**: `order_id, customer_id, transaction_id, product_name, amount, status, created_at`
  — `status` ∈ `completed | abandoned | pending`

Upload daily for the best results — each upload both retrains the risk
view for that day and adds facts to the RAG store the agents draw on,
so accuracy and grounding improve the more days you feed it. Weekly or
monthly batches work too; just tag them with the relevant date.

## Honest limitations (MVP, on purpose)

- SQLite by default — swap `DATABASE_URL` in `.env` for Postgres when you're ready for multi-user/production.
- Recovery probability is a transparent heuristic until you have 25+ real offer outcomes logged (then it can be trained — see `train_from_history()`).
- Auth is a simple JWT bearer token — fine for one merchant locally, add refresh tokens / rate limiting before exposing this publicly.
- No real payment gateway integration — this manages *your own* uploaded transaction records, it doesn't call Razorpay/Stripe etc. (that's the natural Phase-2 extension, per the original product spec).

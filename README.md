AI Spending Dashboard — Weekly \& Monthly Executive Insights



One-click pipeline that pulls bank/credit-card transactions from Plaid, enriches and labels them, generates executive-ready weekly \& MTD insights (JSON/MD/HTML/PDF), emails the digest (inline charts + optional PDF), and feeds a Power BI dashboard. Built with a deterministic pipeline, clear diagnostics, clean visuals, and print-friendly deliverables.



✨ Features



Plaid v14 via /transactions/sync with Personal Finance Categories (PFC).



Layered categorization: YAML mappings → merchant dimension cache → PFC → legacy → “Uncategorized”.



Signals: subscription detection \& per-merchant anomaly Z-scores.



Executive outputs:



Weekly (WoW) \& Monthly (MTD vs prior MTD) JSON, Markdown, HTML, PDF.



Inline charts: 28-day trend, Top Categories donut, WoW Category Movement.



Email: Gmail-ready (STARTTLS/SSL), inline images; optional PDF attachment.



Power BI: curated fact table + “insights\_flat.csv” for tiles.



CI/CD: GitHub Actions to build, enrich, generate, and commit artifacts.



🧭 Repository Layout

scripts/

&nbsp; build\_latest.ipynb           # Pull from Plaid → latest.csv (+ PFC columns)

&nbsp; enrich\_transactions.ipynb    # Labeling, signals, insights, charts, email, PDF

config/

&nbsp; categories.yaml              # Optional hand mappings by merchant\_key

&nbsp; merchants\_dim.csv            # Learned/AI cache of merchant labels (auto-updated)

data/

&nbsp; raw/latest.csv               # Canonical transactions (stable for BI)

&nbsp; processed/latest\_enriched.csv

&nbsp; processed/insights/          # JSON/MD/HTML/PDF + charts (\*.png)

.state/

&nbsp; access\_tokens.json           # (CI) Plaid tokens injected from secrets

&nbsp; plaid\_cursors.json           # Sync cursors per token

.github/workflows/

&nbsp; pull-transactions.yml        # Build \& enrich workflow



⚙️ Requirements



Pin versions (already in requirements.txt):



pandas==2.2.2 · numpy==1.26.4 · pyarrow==16.1.0



plaid-python==14.0.0



openai==1.43.0 · tenacity==8.2.3



httpx==0.26.0 (implicitly pins httpcore 1.x—resolves CI conflicts)



python-dotenv==1.0.1 · PyYAML==6.0.2 · matplotlib==3.8.4



pdfkit==1.0.0 (for PDF via wkhtmltopdf)



jupyter==1.0.0 (local dev)



Install:



python -m pip install --upgrade pip

pip install -r requirements.txt



🔐 Environment \& Secrets (.env)



Create a .env file in the repo root:



\# --- Plaid ---

PLAID\_CLIENT\_ID=...

PLAID\_SECRET=...

PLAID\_ENV=production            # or development/sandbox

\# JSON map of item labels to access\_tokens (one or many)

PLAID\_ACCESS\_TOKENS={"Visa":"access-production-xxxx","Checking":"access-production-yyyy"}



\# --- Azure OpenAI (optional but recommended for narrative) ---

AZURE\_OPENAI\_ENDPOINT=https://<resource>.openai.azure.com

AZURE\_OPENAI\_API\_KEY=...

AZURE\_OPENAI\_DEPLOYMENT=gpt-4o-mini          # chat DEPLOYMENT NAME (not model)

AZURE\_OPENAI\_EMBEDDINGS=text-embedding-3-large  # embeddings DEPLOYMENT NAME

AZURE\_OPENAI\_API\_VERSION=2024-02-15-preview



\# --- Email (start with dry run) ---

EMAIL\_ENABLED=1

EMAIL\_DRY\_RUN=1

SMTP\_HOST=smtp.gmail.com

SMTP\_PORT=587

SMTP\_SSL\_PORT=465

SMTP\_USERNAME=you@gmail.com

SMTP\_PASSWORD=app-password

EMAIL\_FROM=you@gmail.com

EMAIL\_TO=you@gmail.com



\# --- wkhtmltopdf (for PDF generation) ---

\# Windows:

WKHTMLTOPDF\_PATH=C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe

\# macOS (Homebrew):  /usr/local/bin/wkhtmltopdf  or  /opt/homebrew/bin/wkhtmltopdf

\# Ubuntu (CI):       wkhtmltopdf





Azure note: Use deployment names in AZURE\_OPENAI\_DEPLOYMENT and AZURE\_OPENAI\_EMBEDDINGS. Don’t put model IDs there.



🚀 Run Locally

papermill scripts/build\_latest.ipynb scripts/build\_latest.ipynb

papermill scripts/enrich\_transactions.ipynb scripts/enrich\_transactions.ipynb





Key outputs:



data/raw/latest.csv



data/processed/latest\_enriched.csv



data/processed/insights/



digest\_latest.json|.md|.html



digest\_mom.json|.md|.html



digest\_combined\_email.html



executive\_summary.pdf (via wkhtmltopdf)



Charts:

weekly\_spend\_line.png, weekly\_top\_categories\_donut.png, weekly\_category\_movement.png



☁️ GitHub Actions (CI)



Workflow: .github/workflows/pull-transactions.yml



Add repository Secrets:



PLAID\_CLIENT\_ID, PLAID\_SECRET, PLAID\_ENV, PLAID\_ACCESS\_TOKENS



(Optional AI) AZURE\_OPENAI\_ENDPOINT, AZURE\_OPENAI\_API\_KEY, AZURE\_OPENAI\_DEPLOYMENT, AZURE\_OPENAI\_EMBEDDINGS



The workflow runs both notebooks with papermill, writes outputs to data/, and commits if changed.



PDFs in CI (Ubuntu): install wkhtmltopdf first:



\- name: Install wkhtmltopdf (Ubuntu)

&nbsp; run: sudo apt-get update \&\& sudo apt-get install -y wkhtmltopdf





Email defaults: set EMAIL\_DRY\_RUN=1 in CI unless you’re ready to send.



🧠 Categorization Logic (precedence)



YAML (config/categories.yaml) overrides by exact merchant\_key.



merchants\_dim.csv (AI-assisted cache) updated as the pipeline learns.



Plaid PFC (primary/detailed).



Legacy Plaid category (if present).



Fallback: Uncategorized.



Diagnostics in the notebooks clearly show PFC availability and category hit rates.



📈 Power BI Guide (Executive-first)



Primary table: data/processed/latest\_enriched.csv

Insights tables:



data/processed/insights/digest\_latest\_flat.csv (Weekly)



data/processed/insights/digest\_mom\_flat.csv (Monthly)



Recommended pages:



Executive Summary



KPIs: Weekly Spend (WoW Δ%), Income, MTD Spend (MoM MTD Δ%), Subscriptions, Anomalies.



Visuals: 28-day trend line, “Top Categories This Week” donut, WoW Movement bar (This Week – Prior).



Categories



MTD breakdown by category; WoW and MoM pivots; drill‐through to merchants.



Merchants



Vendor list with subscription flag, anomalies, spend sparkline.



Transactions



Paginated detail with slicers (date, card, category, merchant).



Suggested DAX (examples):



WoW Spend Δ% =

VAR Cur = \[Spend (This Week)]

VAR Prev = \[Spend (Last Week)]

RETURN DIVIDE(Cur - Prev, Prev)



MTD Spend Δ% vs Prior MTD =

VAR Cur = \[Spend (MTD)]

VAR Prev = \[Spend (Prior MTD Aligned)]

RETURN DIVIDE(Cur - Prev, Prev)





Use the prebuilt insights\_flat.csv rows for tiles (“header”, “metric”, “driver”, “risk”) or to drive a narrative card.



📨 Email \& PDF



Email body is the combined weekly \& monthly HTML with inline charts.



PDF (print-friendly) is generated by wkhtmltopdf from the HTML.

Ensure WKHTMLTOPDF\_PATH is set correctly.



Attach the PDF if desired (cell shows how; optional).



Kill switches:



Set EMAIL\_ENABLED=0 or create .state/EMAIL\_KILL to block send.



Use EMAIL\_DRY\_RUN=1 while testing credentials.



🔧 Parameters \& Controls



GOAL\_SAVINGS (default 1000) — used for suggested reductions.



ANOMALY\_Z (default 2.5) — per-merchant anomaly threshold.



EMAIL\_ENABLED / EMAIL\_DRY\_RUN — delivery controls.



WKHTMLTOPDF\_PATH — absolute path to the binary (Windows/macOS), or wkhtmltopdf on Linux.



.state/plaid\_cursors.json — maintained automatically for /transactions/sync.



🛠 Troubleshooting



wkhtmltopdf not found / permission error

Use the full path to the executable on Windows, e.g.

C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe

On Ubuntu CI, install with apt-get and set WKHTMLTOPDF\_PATH=wkhtmltopdf.



Azure error: “embeddings operation does not work with model …”

Ensure AZURE\_OPENAI\_EMBEDDINGS is your embeddings deployment (e.g., text-embedding-3-large), not a chat model. Chat deployment (e.g., gpt-4o-mini) goes in AZURE\_OPENAI\_DEPLOYMENT.



PFC all null

Confirm plaid-python==14.0.0 and the items support PFC. Re-run build\_latest.ipynb.



HTTPX/httpcore conflicts in CI

The requirements.txt pins httpx==0.26.0 so it pulls compatible httpcore 1.x.



🔐 Security



Secrets only via .env or GitHub Secrets.



Masked diagnostics; never commit raw keys.



CSVs contain no access tokens or secrets.



🗺 Roadmap (Optional)



Budget targets \& variance alerts per category/merchant.



Multi-user support via item namespace.



Deeper “red flags” explainers on anomalies/subscriptions.



📄 License


MIT © 2025 Kosisonna Francis Ugochukwu. See LICENSE for details.



## 🏗️ Production-Grade Architecture

**NEW:** This project has been refactored for production quality with modular, testable, and observable code.

### Modular Python Codebase (`src/` directory)

- **`logger.py`** — Structured logging with sensitive data masking
- **`monitoring.py`** — Track API calls, LLM costs, processing times
- **`config.py`** — Robust environment variable handling and validation
- **`plaid_client.py`** — Production-ready Plaid SDK wrapper with retries
- **`data_processing.py`** — Merchant normalization, PFC mapping, YAML handling
- **`error_handling.py`** — Retry decorators, circuit breakers, graceful degradation

### Comprehensive Testing (`tests/` directory)

- Unit tests with pytest
- Mock Plaid responses
- Data validation tests
- Run tests: `pytest tests/ -v`

### Monitoring & Observability

- API call tracking (success rate, latency, failures)
- LLM token usage and cost estimation (tokens + USD)
- Processing stage timing
- Metrics exported to `data/processed/insights/metrics.json` and `metrics.csv`

### Production Documentation

- **[`ARCHITECTURE.md`](./ARCHITECTURE.md)** — System design, data flow diagrams, deployment patterns
- **[`PRODUCTION_GUIDE.md`](./PRODUCTION_GUIDE.md)** — Comprehensive guide covering:
  - Security best practices (secrets management, data privacy, input validation)
  - Failure modes & recovery strategies (Plaid API failures, Azure OpenAI quota issues, email delivery)
  - Monitoring & alerting thresholds (critical and warning alerts)
  - Edge cases & known issues (PFC missing, duplicate transactions, PDF generation)
  - Performance optimization (parallel fetching, batch AI categorization, database backends)
  - Operational guidelines (deployment checklist, capacity planning, maintenance tasks)

### Using the Refactored Modules

While the notebooks remain functional, you can now use production modules directly:

```python
from src.config import Config
from src.plaid_client import PlaidClient
from src.data_processing import add_merchant_keys, extract_pfc_categories
from src.monitoring import MetricsCollector

# Initialize
config = Config()
metrics = MetricsCollector()
metrics.start_pipeline()

# Fetch transactions
plaid = PlaidClient(config, metrics=metrics, cursors_path=config.cursors_path)
df = plaid.fetch_all_transactions(days_back=config.days_back)

# Process
df = extract_pfc_categories(df)
df = add_merchant_keys(df)

# Export metrics
metrics.end_pipeline()
metrics.export_json('data/processed/insights/metrics.json')
metrics.export_csv('data/processed/insights/metrics.csv')
```

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_data_processing.py -v
```

### Monitoring Metrics

Metrics are automatically tracked and exported to:
- `data/processed/insights/metrics.json` (structured JSON for programmatic access)
- `data/processed/insights/metrics.csv` (flat CSV for Power BI tiles)

**Tracked Metrics:**
- **API Calls:** Total count, success/failure rates, avg/min/max latency per endpoint
- **LLM Usage:** Tokens consumed (prompt + completion), estimated cost in USD by model
- **Processing:** Stage durations, rows processed, errors encountered
- **Errors:** Last 10 error messages per failed endpoint

Import `metrics.csv` into Power BI to build operational dashboards showing:
- Pipeline health (API success rates over time)
- Cost trends (daily LLM spending)
- Performance metrics (processing duration trends)
- Alert conditions (failures exceeding thresholds)


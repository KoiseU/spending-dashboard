# Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FINANCIAL DASHBOARD SYSTEM                          │
│                         Production-Grade Architecture                        │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                              DATA SOURCES                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │ Plaid API    │     │ Bank APIs    │     │ Credit Cards │                │
│  │              │────▶│              │────▶│              │                │
│  │ Aggregator   │     │ (via Plaid)  │     │ (via Plaid)  │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│                                                                               │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          INGESTION LAYER                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  PlaidClient (src/plaid_client.py)                                  │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │  • Cursor-based incremental sync                              │  │   │
│  │  │  • Personal Finance Category (PFC) extraction                 │  │   │
│  │  │  • Automatic v10/legacy SDK detection                         │  │   │
│  │  │  • Error handling with retries                                │  │   │
│  │  │  • Multi-bank parallel fetching                               │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  Outputs: Raw DataFrame with transactions                                   │
│           ↓                                                                  │
│  ┌────────────────────┐                                                     │
│  │ data/raw/          │                                                     │
│  │   latest.csv       │  ← Canonical source of truth                       │
│  └────────────────────┘                                                     │
│                                                                               │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        PROCESSING LAYER                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  DataProcessing (src/data_processing.py)                            │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │  1. Merchant Key Normalization                                │  │   │
│  │  │     • Aggressive cleanup (POS, DEBIT, store #s removed)       │  │   │
│  │  │     • Brand canonicalization (AMZN → AMAZON)                  │  │   │
│  │  │                                                                │  │   │
│  │  │  2. PFC Mapping                                               │  │   │
│  │  │     • Extract primary/detailed categories                     │  │   │
│  │  │     • Map to friendly names (FOOD_AND_DRINK → Dining)        │  │   │
│  │  │                                                                │  │   │
│  │  │  3. YAML Category Mapping (Optional)                          │  │   │
│  │  │     • Exact merchant_key matches                              │  │   │
│  │  │     • Token-based substring matching                          │  │   │
│  │  │                                                                │  │   │
│  │  │  4. Non-Spend Flow Detection                                  │  │   │
│  │  │     • Flag transfers, payments, refunds                       │  │   │
│  │  │                                                                │  │   │
│  │  │  5. Data Validation                                           │  │   │
│  │  │     • Date range checks                                       │  │   │
│  │  │     • Amount validation                                       │  │   │
│  │  │     • Categorization rate QA                                  │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        ENRICHMENT LAYER                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Azure OpenAI Integration                                           │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │  • AI-Powered Merchant Categorization                         │  │   │
│  │  │    (gpt-4o-mini with caching in merchants_dim.csv)            │  │   │
│  │  │                                                                │  │   │
│  │  │  • Subscription Detection                                     │  │   │
│  │  │    (recurring transactions by merchant)                       │  │   │
│  │  │                                                                │  │   │
│  │  │  • Anomaly Detection                                          │  │   │
│  │  │    (Z-score per merchant, threshold: 2.5σ)                   │  │   │
│  │  │                                                                │  │   │
│  │  │  • AI Narrative Generation                                    │  │   │
│  │  │    (executive insights, recommendations)                      │  │   │
│  │  │                                                                │  │   │
│  │  │  • Embeddings (Optional)                                      │  │   │
│  │  │    (text-embedding-3-large for semantic search)               │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  Outputs:                                                                    │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ data/processed/                                                 │         │
│  │   latest_enriched.csv     ← Enriched transactions             │         │
│  │   insights/                                                     │         │
│  │     digest_latest.json    ← Weekly WoW summary                 │         │
│  │     digest_mom.json       ← Monthly MoM summary                │         │
│  │     metrics.json          ← Monitoring data                    │         │
│  │   config/                                                       │         │
│  │     merchants_dim.csv     ← AI-learned merchant cache         │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                                                               │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          INSIGHTS LAYER                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Analytics & Reporting                                              │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │  • Time Window Segmentation                                   │  │   │
│  │  │    - Weekly (WoW): This week vs. prior week                   │  │   │
│  │  │    - Monthly (MoM): MTD vs. prior month MTD                   │  │   │
│  │  │    - 30-day rolling analysis                                  │  │   │
│  │  │                                                                │  │   │
│  │  │  • Visualizations (Matplotlib)                                │  │   │
│  │  │    - 28-day spend trend line                                  │  │   │
│  │  │    - Top categories donut chart                               │  │   │
│  │  │    - Category movement bar chart                              │  │   │
│  │  │                                                                │  │   │
│  │  │  • Goal Nudges                                                │  │   │
│  │  │    (category-level savings suggestions)                       │  │   │
│  │  │                                                                │  │   │
│  │  │  • Data Quality Reports                                       │  │   │
│  │  │    (dq_report.md with diagnostics)                            │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  Multi-Format Outputs:                                                      │
│  • JSON (structured data)                                                   │
│  • Markdown (human-readable)                                                │
│  • HTML (email-ready with inline charts)                                   │
│  • PDF (print-friendly via wkhtmltopdf)                                    │
│  • CSV (flat format for Power BI tiles)                                    │
│  • PNG (chart images)                                                       │
│                                                                               │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        DELIVERY LAYER                                        │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────────┐      ┌──────────────────────────┐            │
│  │ Email (SMTP)             │      │ Power BI                 │            │
│  │  • HTML digest           │      │  • CSV data sources      │            │
│  │  • PDF attachment        │      │  • Flat metric tiles     │            │
│  │  • Inline charts         │      │  • Auto-refresh via      │            │
│  │  • DRY_RUN mode          │      │    Gateway (optional)    │            │
│  │  • KILL switch           │      └──────────────────────────┘            │
│  └──────────────────────────┘                                               │
│                                                                               │
│  ┌──────────────────────────┐      ┌──────────────────────────┐            │
│  │ Slack/Teams (Webhooks)   │      │ S3/Blob Storage          │            │
│  │  • Alert notifications   │      │  • Archive outputs       │            │
│  │  • Daily summaries       │      │  • Secure file sharing   │            │
│  └──────────────────────────┘      └──────────────────────────┘            │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Cross-Cutting Concerns

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                       OBSERVABILITY & MONITORING                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Monitoring (src/monitoring.py)                                     │   │
│  │  • API call tracking (count, latency, success rate)                 │   │
│  │  • LLM cost estimation (tokens + pricing)                           │   │
│  │  • Processing stage timing                                          │   │
│  │  • Export to JSON/CSV for dashboards                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Logging (src/logger.py)                                            │   │
│  │  • Structured logging (DEBUG, INFO, WARNING, ERROR)                 │   │
│  │  • Sensitive data masking (credentials, tokens)                     │   │
│  │  • JSON output for log aggregation                                  │   │
│  │  • Performance timing decorators                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                          ERROR HANDLING                                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Error Handling (src/error_handling.py)                             │   │
│  │  • Retry with exponential backoff                                   │   │
│  │  • Circuit breaker pattern for external services                    │   │
│  │  • Graceful degradation (non-critical failures don't halt pipeline) │   │
│  │  • Timeout protection                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                        CONFIGURATION                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Config (src/config.py)                                             │   │
│  │  • Multi-format .env loading                                        │   │
│  │  • Token parsing (JSON, pairs, CSV)                                 │   │
│  │  • Path resolution (CI-safe, cross-platform)                        │   │
│  │  • Validation (format checks, required fields)                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
│  Environment Variables:                                                     │
│  • PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV                                │
│  • PLAID_ACCESS_TOKENS (JSON or key=value pairs)                           │
│  • AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT   │
│  • SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO          │
│  • DAYS_BACK (default: 180), GOAL_SAVINGS (default: 1000)                 │
│  • EMAIL_ENABLED, EMAIL_DRY_RUN, EMAIL_KILL switch                         │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagram

```
┌─────────────┐
│   Plaid     │ ──────┐
│   Banks     │       │
└─────────────┘       │
                      │ Fetch (SYNC)
┌─────────────┐       │ • Cursor-based incremental
│  Azure      │       │ • PFC included
│  OpenAI     │       │ • Multi-bank parallel
└──────┬──────┘       │
       │              ▼
       │      ┌───────────────────┐
       │      │   latest.csv      │ ← Raw transactions (canonical)
       │      └────────┬──────────┘
       │               │
       │               │ Process
       │               │ • Merchant key normalization
       │               │ • PFC → friendly names
       │               │ • YAML mapping (optional)
       │               │ • Non-spend detection
       │               │
       │               ▼
       │      ┌────────────────────┐
       │      │ latest_enriched.csv│
       │      └────────┬───────────┘
       │               │
       │               │ Enrich
       │               │ • AI categorization (new merchants)
       │               │ • Subscription detection
       │               │ • Anomaly detection
       │               │
       └───────────────┤
                       │
                       ▼
              ┌─────────────────────┐
              │  merchants_dim.csv  │ ← AI cache (auto-updating)
              └─────────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │ Insights Generation │
              │  • Time segmentation│
              │  • Charts           │
              │  • AI narratives    │
              │  • Goal nudges      │
              └──────────┬──────────┘
                         │
                         ▼
        ┌────────────────┴────────────────┐
        │                                  │
        ▼                                  ▼
   ┌─────────┐                      ┌──────────┐
   │  Email  │                      │ Power BI │
   │  SMTP   │                      │   CSV    │
   └─────────┘                      └──────────┘
        │                                  │
        ▼                                  ▼
   ┌─────────────────────────────────────────┐
   │         End Users / Dashboards          │
   └─────────────────────────────────────────┘
```

---

## Module Dependencies

```
src/
├── __init__.py
├── logger.py               (no internal deps)
├── monitoring.py           (depends: logger)
├── config.py               (depends: logger)
├── error_handling.py       (depends: logger)
├── plaid_client.py         (depends: config, logger, monitoring, error_handling)
├── data_processing.py      (depends: logger)
└── main.py                 (depends: all above)

tests/
├── __init__.py
├── test_logger.py
├── test_monitoring.py
├── test_config.py
├── test_data_processing.py
└── test_plaid_client.py
```

---

## Deployment Patterns

### Pattern 1: GitHub Actions (Current)

```
┌──────────────────────────────────────────────────────────────┐
│                   GitHub Actions Workflow                    │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Trigger: workflow_dispatch (manual) or cron schedule        │
│                                                               │
│  Steps:                                                      │
│  1. Checkout code                                            │
│  2. Install dependencies (pip, wkhtmltopdf)                  │
│  3. Prepare runtime state (.state/, access_tokens.json)      │
│  4. Run build_latest.ipynb (papermill) or python main.py    │
│  5. Run enrich_transactions.ipynb or python enrich.py       │
│  6. Commit outputs (data/raw/, data/processed/)              │
│  7. Send notifications (Slack webhook if configured)         │
│                                                               │
│  Environment: ubuntu-latest, Python 3.11                     │
│  Secrets: Stored in GitHub repository settings               │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Pattern 2: Docker Container (Recommended for Production)

```
┌──────────────────────────────────────────────────────────────┐
│                      Docker Deployment                       │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Dockerfile:                                                 │
│    FROM python:3.11-slim                                     │
│    RUN apt-get update && apt-get install -y wkhtmltopdf     │
│    COPY requirements.txt .                                   │
│    RUN pip install -r requirements.txt                       │
│    COPY src/ /app/src/                                       │
│    CMD ["python", "-m", "src.main"]                          │
│                                                               │
│  Run:                                                        │
│    docker run --env-file .env \                              │
│               -v ./data:/app/data \                          │
│               -v ./config:/app/config \                      │
│               financial-dashboard                            │
│                                                               │
│  Orchestration: Kubernetes CronJob or ECS Scheduled Tasks   │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Pattern 3: Serverless (AWS Lambda / Azure Functions)

```
┌──────────────────────────────────────────────────────────────┐
│                   Serverless Deployment                      │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Trigger: CloudWatch Events (cron) or EventBridge           │
│                                                               │
│  Function:                                                   │
│    - Input: S3 event (new transactions uploaded)            │
│    - Processing: Run enrichment pipeline                     │
│    - Output: Write to S3, send SNS notifications            │
│                                                               │
│  Challenges:                                                 │
│    - 15-minute timeout (Lambda)                              │
│    - wkhtmltopdf requires Lambda Layer or EFS mount          │
│    - State persistence (use S3 or DynamoDB for cursors)     │
│                                                               │
│  Best For: Event-driven, on-demand processing                │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Security Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Security Layers                         │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Secrets Management                                       │
│     • Environment variables (production)                     │
│     • AWS Secrets Manager / Azure Key Vault                  │
│     • Never commit .env or tokens to Git                     │
│                                                               │
│  2. Data Encryption                                          │
│     • At rest: Filesystem encryption (LUKS, BitLocker)       │
│     • In transit: HTTPS for all API calls                    │
│     • Sensitive logs masked (credentials show 1st+last 4)    │
│                                                               │
│  3. Access Control                                           │
│     • File permissions: chmod 600 .env, 700 .state/          │
│     • IAM roles for cloud resources (principle of least)     │
│     • No public S3 buckets or file shares                    │
│                                                               │
│  4. Audit Logging                                            │
│     • All API calls logged with timestamps                   │
│     • Failed auth attempts tracked                           │
│     • Export logs to SIEM for anomaly detection              │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Scalability Considerations

| Dimension         | Current Limit | Bottleneck                 | Solution                          |
|-------------------|---------------|----------------------------|-----------------------------------|
| Transaction Count | ~10K          | CSV in-memory processing   | Migrate to SQLite/PostgreSQL      |
| Bank Accounts     | ~10           | Sequential API calls       | Parallel fetching (ThreadPool)    |
| AI Categorization | ~100 new/run  | 1 API call per merchant    | Batch prompts (10 merchants/call) |
| Report Size       | ~10MB PDF     | wkhtmltopdf single-thread  | Reduce chart DPI, skip PDF        |
| Pipeline Duration | ~5 min        | Sync all banks + AI calls  | Incremental processing only       |

---

**Last Updated**: 2024-12-19

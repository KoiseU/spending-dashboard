## Production Considerations & Edge Cases

This document outlines important considerations for running the Financial Dashboard in production, including security best practices, failure modes, monitoring strategies, and operational guidelines.

---

## 🔒 Security Considerations

### 1. **Secrets Management**

**Current Implementation:**
- Credentials stored in `.env` files or environment variables
- Access tokens in `.state/access_tokens.json` (gitignored)
- Sensitive data masked in logs (first/last 4 characters only)

**Production Recommendations:**
- ✅ **Use dedicated secrets management** (AWS Secrets Manager, Azure Key Vault, HashiCorp Vault)
- ✅ **Rotate credentials regularly** (Plaid access tokens, Azure API keys, SMTP passwords)
- ✅ **Restrict file permissions** on `.env` and `.state/` directories (chmod 600)
- ✅ **Use short-lived tokens** where possible (Plaid offers token rotation)
- ❌ **Never commit** `.env`, `access_tokens.json`, or CSV files with transaction data to version control

**Security Checklist:**
```bash
# Set restrictive permissions
chmod 600 .env
chmod 700 .state/
chmod 600 config/*.csv

# Verify gitignore coverage
git check-ignore .env .state/ data/raw/*.csv data/processed/*.csv

# Audit environment variables
env | grep -E 'PLAID|AZURE|SMTP' | sed 's/=.*/=***/'
```

### 2. **Data Privacy**

**PII in Outputs:**
- ✅ CSV files (`latest.csv`, `latest_enriched.csv`) contain: transaction names, merchant names, amounts, dates
- ✅ Insights (JSON/MD/HTML) contain: aggregated spending, merchant names, category totals
- ❌ **No bank account numbers, SSNs, or full card numbers** are stored (only last 4 digits if using `mask` column)

**Recommendations:**
- Encrypt data at rest (use filesystem encryption or encrypted volumes)
- Restrict access to `data/` directories (use IAM roles, not public S3 buckets)
- Consider anonymizing merchant names in shared reports (hash or pseudonymize)
- GDPR/CCPA compliance: Provide data export/deletion mechanisms if handling multi-user data

### 3. **Input Validation**

**Current Validation:**
- Plaid tokens validated for format (`access-{env}-[a-z0-9-]+`)
- Environment variable normalization (e.g., `prod` → `production`)
- DataFrame validation checks (date ranges, amounts, categorization rates)

**Edge Cases to Handle:**
- ❌ **Malformed Plaid responses** (missing PFC, null `merchant_name`, negative amounts for refunds)
- ❌ **Extremely large amounts** (>$1M triggers anomaly detection; may need custom thresholds)
- ❌ **Unicode/emoji in merchant names** (can break PDF generation with wkhtmltopdf)
- ❌ **Duplicate transaction_ids** (rare but possible; dedupe logic handles this)

**Hardening:**
```python
# Add schema validation
from pydantic import BaseModel, validator

class Transaction(BaseModel):
    transaction_id: str
    amount: float
    date: str

    @validator('amount')
    def amount_must_be_reasonable(cls, v):
        if abs(v) > 1_000_000:
            raise ValueError('Amount exceeds $1M threshold')
        return v
```

---

## ⚠️ Failure Modes & Recovery

### 1. **Plaid API Failures**

**Failure Scenarios:**
- **Rate limiting** (429 Too Many Requests): 5 requests/second limit for `/transactions/sync`
- **Invalid access token** (400 Bad Request): Token expired or revoked
- **Service outage** (500 Internal Server Error): Plaid downtime
- **Network timeout**: Connection issues

**Current Handling:**
- ✅ Exceptions logged with full stack trace
- ❌ No automatic retry (relies on CI/CD workflow rerun)

**Recommended Improvements:**
```python
from src.error_handling import retry_with_backoff, CircuitBreaker

plaid_breaker = CircuitBreaker(failure_threshold=5, timeout=60)

@retry_with_backoff(max_attempts=4, initial_delay=2.0, exceptions=(NetworkError, Timeout))
@plaid_breaker
def sync_transactions():
    # Your Plaid API call
    ...
```

**Recovery:**
- **Rate limit**: Implement exponential backoff (2s, 4s, 8s, 16s)
- **Invalid token**: Alert operator, require manual re-authentication
- **Outage**: Use cached data from previous run, skip sync until next schedule

### 2. **Azure OpenAI Failures**

**Failure Scenarios:**
- **Quota exceeded** (429): Free tier limits or max tokens/minute
- **Content filter triggered** (400): Transaction description flagged as unsafe
- **Model unavailable** (503): Deployment not found or region outage

**Current Handling:**
- ✅ Tenacity retry wrapper (3 attempts with exponential backoff)
- ❌ No fallback categorization if AI fails

**Graceful Degradation:**
```python
from src.error_handling import GracefulDegradation

with GracefulDegradation("azure_openai", default_value=None):
    category = call_azure_openai_categorization(merchant)

if category is None:
    # Fallback to rule-based categorization
    category = fallback_categorize(merchant)
```

**Cost Controls:**
- Monitor token usage in `metrics.json` (see Monitoring section)
- Set Azure OpenAI spending alerts (Budget + Action Group in Azure Portal)
- Cache AI responses in `merchants_dim.csv` to avoid re-categorizing same merchants

### 3. **Email Delivery Failures**

**Failure Scenarios:**
- **SMTP authentication failure** (535): Wrong username/password
- **Attachment too large** (552): PDF + embedded images exceed 25MB
- **Recipient rejected** (550): Invalid email address

**Current Handling:**
- ✅ `EMAIL_KILL` switch (`.state/EMAIL_KILL` suppresses all sends)
- ✅ `EMAIL_DRY_RUN` mode (logs email but doesn't send)
- ❌ No retry on transient failures

**Recommendations:**
- Use SendGrid/AWS SES for better deliverability (vs. Gmail SMTP)
- Split large emails (send PDF as link instead of attachment)
- Validate email addresses before sending

### 4. **Data Corruption**

**Scenarios:**
- **Cursor corruption**: `plaid_cursors.json` contains invalid JSON
- **CSV truncation**: Partial write due to disk full or kill signal
- **Merchant dimension drift**: AI misclassifies existing merchants on re-run

**Mitigation:**
- ✅ Atomic writes (write to temp file, then rename)
- ✅ Keep previous `latest.csv` as backup (SYNC merges with it)
- ❌ No checksums or file integrity validation

**Backup Strategy:**
```bash
# Daily snapshots
cp data/raw/latest.csv data/raw/backups/latest_$(date +%Y%m%d).csv

# Retention: keep last 30 days
find data/raw/backups/ -name 'latest_*.csv' -mtime +30 -delete
```

---

## 📊 Monitoring & Observability

### 1. **Metrics to Track**

**API Metrics** (tracked in `monitoring.py`):
- ✅ Total API calls (Plaid, Azure OpenAI)
- ✅ Success/failure rates
- ✅ Latency (avg, min, max)
- ✅ Error messages (last 10)

**LLM Cost Metrics:**
- ✅ Token usage (prompt, completion, total)
- ✅ Estimated cost in USD (using latest pricing)
- ✅ Failed requests

**Processing Metrics:**
- ✅ Stage duration (data ingestion, enrichment, insights generation)
- ✅ Rows processed
- ✅ Warnings/errors encountered

**Outputs:**
- `data/processed/insights/metrics.json` (structured JSON)
- `data/processed/insights/metrics.csv` (flat CSV for Power BI)

### 2. **Alerting Thresholds**

**Critical Alerts:**
- ❌ Plaid API failure rate > 20%
- ❌ Zero transactions fetched (possible auth issue)
- ❌ Enrichment pipeline duration > 10 minutes (SLA breach)
- ❌ LLM cost > $5/run (budget exceeded)

**Warning Alerts:**
- ⚠️ Uncategorized transactions > 30%
- ⚠️ Anomaly detection flags > 10% of transactions
- ⚠️ Email delivery failed (DRY_RUN=0 but send failed)

**Implementation:**
```python
# In CI/CD workflow (GitHub Actions)
- name: Check metrics
  run: |
    FAILURE_RATE=$(jq '.api_calls["plaid.transactions.sync"].failed' metrics.json)
    if [ "$FAILURE_RATE" -gt 2 ]; then
      echo "::error::High Plaid failure rate: $FAILURE_RATE"
      exit 1
    fi
```

### 3. **Log Aggregation**

**Current Logging:**
- ✅ Structured logs (INFO, WARNING, ERROR levels)
- ✅ Sensitive data masking
- ✅ Timing decorators for performance tracking

**Production Enhancements:**
- Send logs to centralized service (Datadog, CloudWatch, ELK stack)
- Enable JSON logging for easier parsing (`json_format=True` in logger setup)
- Add correlation IDs to trace requests across services

**Example:**
```python
from src.logger import setup_logger

logger = setup_logger(
    name="financial_dashboard",
    level=logging.INFO,
    log_file=Path("/var/log/financial-dashboard/app.log"),
    json_format=True  # Enable for log aggregation
)
```

---

## 🔧 Operational Guidelines

### 1. **Deployment Checklist**

**Pre-Deployment:**
- [ ] Run unit tests (`pytest tests/`)
- [ ] Validate `.env` configuration (all required vars present)
- [ ] Test with `EMAIL_DRY_RUN=1` and `PRECHECK=1`
- [ ] Verify wkhtmltopdf installed (`which wkhtmltopdf`)
- [ ] Check disk space (need ~500MB for outputs + logs)

**Deployment:**
- [ ] Deploy new code to production environment
- [ ] Restart services/CI workflows
- [ ] Monitor logs for first run (check for errors)
- [ ] Validate outputs (CSV row counts, JSON structure)

**Post-Deployment:**
- [ ] Review metrics.json for anomalies
- [ ] Check email delivery (if enabled)
- [ ] Update Power BI data sources (if paths changed)

### 2. **Capacity Planning**

**Resource Requirements:**
- **CPU**: 1-2 cores (mostly I/O-bound, not CPU-intensive)
- **Memory**: 512MB-1GB (depends on transaction volume; 10K txns ≈ 100MB RAM)
- **Disk**: 1GB (CSV + JSON + logs; increases with retention)
- **Network**: ~5-10MB per run (API calls + image embedding in emails)

**Scaling Considerations:**
- **Transaction volume > 50K**: Batch processing or database backend recommended (CSV becomes slow)
- **Multiple users/accounts**: Need multi-tenancy (separate data directories per user)
- **Real-time updates**: Current architecture is batch-only (runs every X hours); consider streaming for real-time

### 3. **Maintenance Tasks**

**Daily:**
- Monitor CI/CD workflow runs (GitHub Actions logs)
- Check `metrics.json` for cost/error trends

**Weekly:**
- Review `dq_report.md` (data quality diagnostics)
- Audit uncategorized transactions (add to `categories.yaml` if needed)
- Rotate logs (keep last 7 days)

**Monthly:**
- Rotate Plaid access tokens (if using token refresh flow)
- Review Azure OpenAI spending (compare estimated vs. actual)
- Clean up old backups (keep last 30 days)
- Update dependencies (`pip list --outdated`, test before upgrading)

**Quarterly:**
- Security audit (check for exposed secrets, outdated packages with CVEs)
- Performance review (identify slow SQL queries, optimize merchant_dim lookups)
- Review anomaly thresholds (adjust `ANOMALY_Z` if too many false positives)

---

## 🐛 Edge Cases & Known Issues

### 1. **Plaid-Specific Edge Cases**

**Issue: Missing Personal Finance Category (PFC)**
- **Cause**: Some banks don't provide PFC, or Plaid categorization failed
- **Impact**: Transactions fall back to legacy Plaid category or "Uncategorized"
- **Mitigation**: Use YAML mapping or AI categorization for uncategorized merchants

**Issue: Duplicate transactions after account re-link**
- **Cause**: New access token generates new `transaction_id` for same txn
- **Impact**: Duplicate rows in CSV (detected by amount+date+account_id match)
- **Mitigation**: Dedupe by `(account_id, date, amount, name)` fallback (already implemented)

**Issue: Pending transactions disappear**
- **Cause**: Plaid returns `pending=True`, then txn is removed before posting
- **Impact**: Temporarily inflated spending totals
- **Mitigation**: Filter `pending=True` transactions in analysis (optional)

### 2. **AI Categorization Edge Cases**

**Issue: Vague merchant names**
- **Example**: "SQ *JANE DOE" (Square payment to individual)
- **AI Guess**: May default to "Services" with low confidence
- **Mitigation**: Manual review of low-confidence (<0.7) merchants

**Issue: Multi-category merchants**
- **Example**: "TARGET" (groceries, clothing, electronics, household)
- **AI Default**: Usually picks most common category (Shopping)
- **Mitigation**: Use per-merchant subcategories or split transactions manually

**Issue: Unicode/emoji in prompts**
- **Example**: Merchant name with emoji ("Starbucks ☕")
- **Impact**: Azure OpenAI may strip or misinterpret characters
- **Mitigation**: Pre-process merchant names (strip non-ASCII) before AI call

### 3. **PDF Generation Edge Cases**

**Issue: wkhtmltopdf not found**
- **Cause**: Not installed or wrong PATH
- **Fix**: Install via `apt-get install wkhtmltopdf` (Linux) or download binary (Windows/macOS)

**Issue: Font rendering issues**
- **Cause**: Missing fonts for Unicode characters (Chinese, Arabic, emoji)
- **Fix**: Install comprehensive font pack (`apt-get install fonts-noto`)

**Issue: Large PDF size (>10MB)**
- **Cause**: Embedded high-resolution PNG charts
- **Fix**: Reduce chart DPI in matplotlib (`dpi=72` instead of 300)

### 4. **Time Zone Edge Cases**

**Issue: Transactions dated in future**
- **Cause**: Plaid returns UTC timestamps, local timezone is behind
- **Impact**: Transactions appear "tomorrow" in reports
- **Mitigation**: Convert all dates to local timezone before analysis

**Issue: Week boundaries differ from user expectation**
- **Cause**: Week-over-week (WoW) uses Monday-Sunday (ISO week)
- **User expects**: Sunday-Saturday (US convention)
- **Mitigation**: Make week start day configurable (add `WEEK_START=SUN` env var)

---

## 📈 Performance Optimization

### 1. **Current Bottlenecks**

**Plaid API Calls:**
- Sync takes ~2-5 seconds per bank (500 txns/page, multiple pages possible)
- Parallel fetching not implemented (sequential per bank)

**Azure OpenAI Categorization:**
- ~1 second per merchant (first time)
- Cached in `merchants_dim.csv` (subsequent runs skip AI)

**PDF Generation:**
- wkhtmltopdf takes ~3-5 seconds (single-threaded)

**Total Pipeline Duration:**
- 3 banks, 200 txns, 5 new merchants: ~30-60 seconds
- 10 banks, 5K txns, 50 new merchants: ~5-10 minutes

### 2. **Optimization Strategies**

**Parallel Bank Fetching:**
```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(sync_bank, bank, token) for bank, token in tokens.items()]
    results = [f.result() for f in futures]
```

**Batch AI Categorization:**
- Send multiple merchants in one prompt (JSON array)
- Reduces API round-trips (10 merchants → 1 call instead of 10)

**Incremental Processing:**
- Only process new/modified transactions (SYNC does this automatically)
- Skip insights generation if no new data (check `latest.csv` mtime)

**Database Backend:**
- For >10K transactions, migrate from CSV to SQLite/PostgreSQL
- Indexed queries 10-100x faster than pandas `df[df.category == 'Dining']`

---

## 🔗 Integration Points

### 1. **Power BI**

**Current Integration:**
- Manual CSV import (refresh data source in Power BI Desktop)
- Flat CSVs for tiles (`digest_latest_flat.csv`, `digest_mom_flat.csv`)

**Production Enhancements:**
- **Power BI Gateway**: Scheduled refresh (hourly/daily) without manual import
- **Direct Query**: Connect to SQL database instead of CSV
- **REST API**: Power BI can fetch from custom API endpoint (more secure than file share)

### 2. **Slack/Teams Notifications**

**Webhook Integration:**
```python
import requests

def send_slack_alert(message):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    requests.post(webhook_url, json={"text": message})

# In error handling
try:
    process_transactions()
except Exception as e:
    send_slack_alert(f"🚨 Pipeline failed: {e}")
```

### 3. **CI/CD Orchestration**

**GitHub Actions (current):**
- ✅ Manual trigger (`workflow_dispatch`)
- ❌ No scheduling (cron-based runs)

**Enhancements:**
```yaml
on:
  schedule:
    - cron: '0 6 * * *'  # Daily at 6 AM UTC
  workflow_dispatch:     # Keep manual trigger
```

**Alternative: Airflow/Prefect**
- Better for complex DAGs (e.g., retry individual stages, parallel processing)
- Monitoring UI, task dependencies, SLA tracking

---

## 🧪 Testing Strategy

### 1. **Current Test Coverage**

**Unit Tests:**
- ✅ `test_data_processing.py` (merchant key normalization, PFC extraction, validation)
- ❌ Missing: Plaid client tests, monitoring tests, config tests

**Integration Tests:**
- ❌ No end-to-end tests (run full pipeline with mock data)

**Smoke Tests:**
- ❌ No automated checks after deployment

### 2. **Recommended Test Additions**

**Mock Plaid Responses:**
```python
@pytest.fixture
def mock_plaid_sync():
    with patch('plaid.api.plaid_api.PlaidApi.transactions_sync') as mock:
        mock.return_value.to_dict.return_value = {
            "added": [...],
            "modified": [],
            "removed": [],
            "has_more": False,
            "next_cursor": "cursor123"
        }
        yield mock
```

**End-to-End Test:**
```bash
# test_e2e.sh
export PLAID_ENV=sandbox
export EMAIL_DRY_RUN=1
python -m src.main  # Run full pipeline
assert [ -f data/processed/insights/metrics.json ]
assert [ $(jq '.totals.total_api_calls' metrics.json) -gt 0 ]
```

---

## 📚 Additional Resources

- **Plaid API Docs**: https://plaid.com/docs/api/products/transactions/
- **Azure OpenAI Pricing**: https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/
- **wkhtmltopdf Manual**: https://wkhtmltopdf.org/usage/wkhtmltopdf.txt
- **Power BI REST API**: https://learn.microsoft.com/en-us/rest/api/power-bi/

---

**Last Updated**: 2024-12-19
**Maintained By**: Financial Dashboard Team

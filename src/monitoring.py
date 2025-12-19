"""
Monitoring and Observability Module

Tracks key metrics for production monitoring:
- API call counts and failures
- LLM costs (tokens and estimated $)
- Processing times
- Data quality metrics
- Export metrics to JSON/CSV for dashboards
"""

import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict, field
from collections import defaultdict


@dataclass
class APIMetrics:
    """Metrics for a single API endpoint."""
    endpoint: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    errors: List[str] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_calls == 0:
            return 0.0
        return (self.successful_calls / self.total_calls) * 100


@dataclass
class LLMMetrics:
    """Metrics for LLM usage and costs."""
    model: str
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    failed_requests: int = 0

    # Pricing per 1M tokens (update as needed)
    PRICING = {
        'gpt-4o-mini': {'prompt': 0.15, 'completion': 0.60},  # per 1M tokens
        'gpt-4o': {'prompt': 2.50, 'completion': 10.00},
        'gpt-4': {'prompt': 30.00, 'completion': 60.00},
        'text-embedding-3-large': {'prompt': 0.13, 'completion': 0.0},
        'text-embedding-3-small': {'prompt': 0.02, 'completion': 0.0},
    }

    def add_request(self, prompt_tokens: int, completion_tokens: int, success: bool = True):
        """Record a new LLM request."""
        self.total_requests += 1
        if not success:
            self.failed_requests += 1
            return

        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += (prompt_tokens + completion_tokens)

        # Calculate cost
        pricing = self.PRICING.get(self.model, {'prompt': 0, 'completion': 0})
        prompt_cost = (prompt_tokens / 1_000_000) * pricing['prompt']
        completion_cost = (completion_tokens / 1_000_000) * pricing['completion']
        self.estimated_cost_usd += (prompt_cost + completion_cost)


@dataclass
class ProcessingMetrics:
    """Metrics for data processing stages."""
    stage: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    rows_processed: int = 0
    errors_encountered: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Calculate processing duration."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0


class MetricsCollector:
    """
    Thread-safe metrics collector for the entire pipeline.

    Usage:
        metrics = MetricsCollector()

        # Track API call
        with metrics.track_api_call('plaid.transactions.sync'):
            response = plaid_client.transactions_sync(...)

        # Track LLM usage
        metrics.record_llm_usage('gpt-4o-mini', prompt_tokens=100, completion_tokens=50)

        # Export metrics
        metrics.export_json('data/processed/insights/metrics.json')
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.api_metrics: Dict[str, APIMetrics] = defaultdict(lambda: APIMetrics(endpoint=""))
        self.llm_metrics: Dict[str, LLMMetrics] = {}
        self.processing_metrics: Dict[str, ProcessingMetrics] = {}
        self.pipeline_start_time: Optional[float] = None
        self.pipeline_end_time: Optional[float] = None
        self.metadata: Dict[str, Any] = {
            'session_id': datetime.utcnow().strftime('%Y%m%d_%H%M%S'),
            'start_timestamp': datetime.utcnow().isoformat(),
        }

    def start_pipeline(self):
        """Mark the start of the entire pipeline."""
        with self._lock:
            self.pipeline_start_time = time.time()

    def end_pipeline(self):
        """Mark the end of the entire pipeline."""
        with self._lock:
            self.pipeline_end_time = time.time()
            self.metadata['end_timestamp'] = datetime.utcnow().isoformat()
            if self.pipeline_start_time:
                self.metadata['total_duration_seconds'] = round(
                    self.pipeline_end_time - self.pipeline_start_time, 2
                )

    def track_api_call(self, endpoint: str):
        """
        Context manager to track an API call.

        Usage:
            with metrics.track_api_call('plaid.sync'):
                result = api_call()
        """
        return _APICallTracker(self, endpoint)

    def record_api_call(
        self,
        endpoint: str,
        latency_ms: float,
        success: bool = True,
        error: Optional[str] = None
    ):
        """Record an API call manually."""
        with self._lock:
            if endpoint not in self.api_metrics:
                self.api_metrics[endpoint] = APIMetrics(endpoint=endpoint)

            metrics = self.api_metrics[endpoint]
            metrics.total_calls += 1

            if success:
                metrics.successful_calls += 1
            else:
                metrics.failed_calls += 1
                if error:
                    metrics.errors.append(error)

            metrics.total_latency_ms += latency_ms

            if metrics.min_latency_ms is None or latency_ms < metrics.min_latency_ms:
                metrics.min_latency_ms = latency_ms

            if metrics.max_latency_ms is None or latency_ms > metrics.max_latency_ms:
                metrics.max_latency_ms = latency_ms

    def record_llm_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
        success: bool = True
    ):
        """Record LLM usage and calculate costs."""
        with self._lock:
            if model not in self.llm_metrics:
                self.llm_metrics[model] = LLMMetrics(model=model)

            self.llm_metrics[model].add_request(prompt_tokens, completion_tokens, success)

    def start_processing_stage(self, stage: str) -> ProcessingMetrics:
        """Start tracking a processing stage."""
        with self._lock:
            metrics = ProcessingMetrics(stage=stage, start_time=time.time())
            self.processing_metrics[stage] = metrics
            return metrics

    def end_processing_stage(self, stage: str, rows_processed: int = 0):
        """End tracking a processing stage."""
        with self._lock:
            if stage in self.processing_metrics:
                self.processing_metrics[stage].end_time = time.time()
                self.processing_metrics[stage].rows_processed = rows_processed

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all collected metrics."""
        with self._lock:
            summary = {
                'metadata': self.metadata,
                'api_calls': {
                    endpoint: {
                        'total': m.total_calls,
                        'successful': m.successful_calls,
                        'failed': m.failed_calls,
                        'success_rate_pct': round(m.success_rate, 2),
                        'avg_latency_ms': round(m.avg_latency_ms, 2),
                        'min_latency_ms': m.min_latency_ms,
                        'max_latency_ms': m.max_latency_ms,
                        'errors': m.errors[-10:],  # Last 10 errors
                    }
                    for endpoint, m in self.api_metrics.items()
                },
                'llm_usage': {
                    model: {
                        'requests': m.total_requests,
                        'failed_requests': m.failed_requests,
                        'prompt_tokens': m.total_prompt_tokens,
                        'completion_tokens': m.total_completion_tokens,
                        'total_tokens': m.total_tokens,
                        'estimated_cost_usd': round(m.estimated_cost_usd, 4),
                    }
                    for model, m in self.llm_metrics.items()
                },
                'processing_stages': {
                    stage: {
                        'duration_seconds': round(m.duration_seconds, 2),
                        'rows_processed': m.rows_processed,
                        'errors': m.errors_encountered,
                        'warnings': m.warnings,
                    }
                    for stage, m in self.processing_metrics.items()
                },
            }

            # Aggregate totals
            summary['totals'] = {
                'total_api_calls': sum(m.total_calls for m in self.api_metrics.values()),
                'total_api_failures': sum(m.failed_calls for m in self.api_metrics.values()),
                'total_llm_requests': sum(m.total_requests for m in self.llm_metrics.values()),
                'total_llm_tokens': sum(m.total_tokens for m in self.llm_metrics.values()),
                'total_llm_cost_usd': round(sum(m.estimated_cost_usd for m in self.llm_metrics.values()), 4),
            }

            return summary

    def export_json(self, file_path: Path | str):
        """Export metrics to JSON file."""
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        summary = self.get_summary()
        with open(file_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

    def export_csv(self, file_path: Path | str):
        """Export metrics to flat CSV for easy Power BI import."""
        import csv

        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        summary = self.get_summary()

        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['category', 'metric', 'value', 'unit'])

            # Metadata
            for key, value in summary['metadata'].items():
                writer.writerow(['metadata', key, value, ''])

            # API metrics
            for endpoint, metrics in summary['api_calls'].items():
                writer.writerow(['api', f'{endpoint}.total_calls', metrics['total'], 'count'])
                writer.writerow(['api', f'{endpoint}.success_rate', metrics['success_rate_pct'], 'percent'])
                writer.writerow(['api', f'{endpoint}.avg_latency', metrics['avg_latency_ms'], 'ms'])

            # LLM metrics
            for model, metrics in summary['llm_usage'].items():
                writer.writerow(['llm', f'{model}.requests', metrics['requests'], 'count'])
                writer.writerow(['llm', f'{model}.total_tokens', metrics['total_tokens'], 'tokens'])
                writer.writerow(['llm', f'{model}.cost', metrics['estimated_cost_usd'], 'usd'])

            # Processing metrics
            for stage, metrics in summary['processing_stages'].items():
                writer.writerow(['processing', f'{stage}.duration', metrics['duration_seconds'], 'seconds'])
                writer.writerow(['processing', f'{stage}.rows', metrics['rows_processed'], 'count'])

            # Totals
            for key, value in summary['totals'].items():
                writer.writerow(['totals', key, value, ''])


class _APICallTracker:
    """Context manager for tracking API calls."""

    def __init__(self, collector: MetricsCollector, endpoint: str):
        self.collector = collector
        self.endpoint = endpoint
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (time.time() - self.start_time) * 1000
        success = exc_type is None
        error = str(exc_val) if exc_val else None

        self.collector.record_api_call(
            endpoint=self.endpoint,
            latency_ms=latency_ms,
            success=success,
            error=error
        )

        # Don't suppress exceptions
        return False


# Global metrics collector instance
global_metrics = MetricsCollector()


if __name__ == "__main__":
    # Demo usage
    metrics = MetricsCollector()
    metrics.start_pipeline()

    # Simulate API calls
    with metrics.track_api_call('plaid.transactions.sync'):
        time.sleep(0.1)

    with metrics.track_api_call('azure.openai.chat'):
        time.sleep(0.05)
        metrics.record_llm_usage('gpt-4o-mini', prompt_tokens=100, completion_tokens=50)

    # Simulate processing
    metrics.start_processing_stage('data_ingestion')
    time.sleep(0.1)
    metrics.end_processing_stage('data_ingestion', rows_processed=158)

    metrics.end_pipeline()

    # Export
    print(json.dumps(metrics.get_summary(), indent=2))

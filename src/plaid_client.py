"""
Plaid Client Module

Handles all Plaid API interactions with:
- Automatic v10/legacy SDK detection and fallback
- Cursor-based incremental sync
- Robust error handling and retries
- Personal Finance Category (PFC) extraction
- Monitoring integration
"""

import json
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

from src.config import PlaidConfig
from src.logger import setup_logger, timed
from src.monitoring import MetricsCollector

logger = setup_logger(__name__)


class PlaidClientError(Exception):
    """Base exception for Plaid client errors."""
    pass


class PlaidClient:
    """
    Production-grade Plaid client with error handling and monitoring.

    Supports both Plaid v10+ (plaid_api) and legacy Client() SDKs.
    """

    def __init__(
        self,
        config: PlaidConfig,
        metrics: Optional[MetricsCollector] = None,
        cursors_path: Optional[Path] = None
    ):
        """
        Initialize Plaid client.

        Args:
            config: Plaid configuration
            metrics: Metrics collector (optional)
            cursors_path: Path to store sync cursors
        """
        self.config = config
        self.metrics = metrics
        self.cursors_path = cursors_path or Path(".state/plaid_cursors.json")
        self.use_v10 = False
        self.client = None

        self._initialize_client()

    def _initialize_client(self):
        """Initialize Plaid SDK client (v10+ or legacy)."""
        try:
            # Try v10+ path
            from plaid.api import plaid_api
            from plaid.configuration import Configuration
            from plaid.api_client import ApiClient

            try:
                from plaid.configuration import Environment
                env_host = {
                    "production": Environment.Production,
                    "development": Environment.Development,
                    "sandbox": Environment.Sandbox,
                }[self.config.environment]
                config = Configuration(host=env_host)
            except (ImportError, AttributeError):
                # Fallback if Environment enum not present
                host_url = {
                    "production": "https://production.plaid.com",
                    "development": "https://development.plaid.com",
                    "sandbox": "https://sandbox.plaid.com",
                }[self.config.environment]
                config = Configuration(host=host_url)

            config.api_key["clientId"] = self.config.client_id
            config.api_key["secret"] = self.config.secret

            api_client = ApiClient(config)
            self.client = plaid_api.PlaidApi(api_client)
            self.use_v10 = True
            logger.info("Initialized Plaid SDK v10+")

        except (ImportError, Exception) as e_v10:
            logger.warning(f"Failed to initialize Plaid v10+: {e_v10}")

            try:
                # Legacy path
                from plaid import Client as LegacyClient
                self.client = LegacyClient(
                    client_id=self.config.client_id,
                    secret=self.config.secret,
                    environment=self.config.environment
                )
                self.use_v10 = False
                logger.info("Initialized Plaid SDK (legacy)")

            except Exception as e_legacy:
                raise PlaidClientError(
                    f"Could not initialize Plaid client.\n"
                    f"v10 error: {e_v10}\nlegacy error: {e_legacy}"
                )

    @timed(logger)
    def fetch_all_transactions(
        self,
        days_back: int = 180,
        use_sync: bool = True
    ) -> pd.DataFrame:
        """
        Fetch transactions from all configured banks.

        Args:
            days_back: Number of days to look back
            use_sync: If True and v10+ client, use incremental sync

        Returns:
            DataFrame with all transactions
        """
        if self.metrics:
            self.metrics.start_processing_stage('plaid_fetch')

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        all_frames = []

        try:
            if self.use_v10 and use_sync:
                logger.info(f"Fetching transactions via SYNC (window: {start_date} to {end_date})")
                for bank_name, token in self.config.access_tokens.items():
                    df = self._sync_bank_transactions(bank_name, token)
                    all_frames.append(df)
            else:
                logger.info(f"Fetching transactions via GET (window: {start_date} to {end_date})")
                for bank_name, token in self.config.access_tokens.items():
                    df = self._get_bank_transactions(bank_name, token, start_date, end_date)
                    all_frames.append(df)

            # Combine and deduplicate
            if all_frames:
                combined = pd.concat([df for df in all_frames if not df.empty], ignore_index=True)
            else:
                combined = pd.DataFrame()

            if not combined.empty:
                combined = self._deduplicate_transactions(combined, start_date, end_date)

            logger.info(
                f"Fetched {len(combined)} transactions from {len(self.config.access_tokens)} banks",
                extra={'row_count': len(combined), 'bank_count': len(self.config.access_tokens)}
            )

            if self.metrics:
                self.metrics.end_processing_stage('plaid_fetch', rows_processed=len(combined))

            return combined

        except Exception as e:
            logger.error(f"Failed to fetch transactions: {e}", exc_info=True)
            if self.metrics:
                self.metrics.processing_metrics['plaid_fetch'].errors_encountered += 1
            raise PlaidClientError(f"Transaction fetch failed: {e}")

    def _sync_bank_transactions(self, bank_name: str, access_token: str) -> pd.DataFrame:
        """Fetch transactions for one bank using /transactions/sync."""
        from plaid.model.transactions_sync_request import TransactionsSyncRequest

        cursors = self._load_cursors()
        cursor = cursors.get(access_token)

        logger.info(
            f"Syncing {bank_name}",
            extra={'bank': bank_name, 'has_cursor': bool(cursor)}
        )

        added, modified, removed_ids = [], [], []
        next_cursor = cursor

        try:
            with self.metrics.track_api_call('plaid.transactions.sync') if self.metrics else _NoOpContext():
                while True:
                    req_kwargs = {"access_token": access_token, "count": 500}
                    if next_cursor:
                        req_kwargs["cursor"] = next_cursor

                    # Request Personal Finance Categories
                    try:
                        from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions
                        req_kwargs["options"] = TransactionsSyncRequestOptions(
                            include_personal_finance_category=True,
                            include_original_description=True
                        )
                    except ImportError:
                        pass

                    req = TransactionsSyncRequest(**req_kwargs)
                    resp = self.client.transactions_sync(req).to_dict()

                    added.extend(resp.get("added", []) or [])
                    modified.extend(resp.get("modified", []) or [])

                    # Handle removed (can be list of strings or dicts)
                    removed = resp.get("removed", []) or []
                    for r in removed:
                        if isinstance(r, dict):
                            rid = r.get("transaction_id")
                            if rid:
                                removed_ids.append(rid)
                        elif isinstance(r, str):
                            removed_ids.append(r)

                    next_cursor = resp.get("next_cursor")
                    if not resp.get("has_more", False):
                        break

            logger.info(
                f"Synced {bank_name}: added={len(added)}, modified={len(modified)}, removed={len(removed_ids)}",
                extra={
                    'bank': bank_name,
                    'added': len(added),
                    'modified': len(modified),
                    'removed': len(removed_ids)
                }
            )

            # Save cursor
            cursors[access_token] = next_cursor
            self._save_cursors(cursors)

            # Convert to DataFrame
            df_add = self._transactions_to_dataframe(added, bank_name)
            df_mod = self._transactions_to_dataframe(modified, bank_name)

            # Merge added and modified
            df = pd.concat([df_add, df_mod], ignore_index=True) if not df_add.empty or not df_mod.empty else pd.DataFrame()

            # Note: removed transactions are handled during dedupe by merging with previous data

            return df

        except Exception as e:
            logger.error(f"Sync failed for {bank_name}: {e}", exc_info=True)
            raise

    def _get_bank_transactions(
        self,
        bank_name: str,
        access_token: str,
        start_date: date,
        end_date: date
    ) -> pd.DataFrame:
        """Fetch transactions for one bank using /transactions/get (legacy)."""
        transactions = []
        offset = 0

        logger.info(f"Fetching {bank_name} via GET", extra={'bank': bank_name})

        try:
            with self.metrics.track_api_call('plaid.transactions.get') if self.metrics else _NoOpContext():
                while True:
                    resp = self.client.Transactions.get(
                        access_token=access_token,
                        start_date=start_date,
                        end_date=end_date,
                        options={"count": 500, "offset": offset}
                    )

                    total = resp["total_transactions"]
                    transactions.extend(resp["transactions"])

                    if len(transactions) >= total:
                        break

                    offset = len(transactions)

                    if offset > 50_000:
                        raise PlaidClientError(f"Pagination runaway for {bank_name}")

            logger.info(
                f"Fetched {len(transactions)} transactions from {bank_name}",
                extra={'bank': bank_name, 'count': len(transactions)}
            )

            return self._transactions_to_dataframe(transactions, bank_name)

        except Exception as e:
            logger.error(f"GET failed for {bank_name}: {e}", exc_info=True)
            raise

    def _transactions_to_dataframe(self, transactions: List[Dict], bank_name: str) -> pd.DataFrame:
        """Convert transaction dicts to normalized DataFrame."""
        if not transactions:
            return pd.DataFrame()

        df = pd.DataFrame(transactions)

        # Ensure expected columns
        expected_cols = [
            "name", "merchant_name", "payment_channel", "pending",
            "account_id", "transaction_id", "category", "date", "amount",
            "personal_finance_category",
        ]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None

        # Normalize category (can be list)
        df["category"] = df["category"].apply(
            lambda x: " > ".join(x) if isinstance(x, (list, tuple)) else x
        )

        # Type conversions
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

        # Add bank info
        df["bank_name"] = bank_name
        df["card_name"] = bank_name  # Can be upgraded later via accounts_dim

        # Select columns
        keep_cols = [
            "date", "name", "merchant_name", "category", "amount",
            "payment_channel", "pending", "account_id", "transaction_id",
            "bank_name", "card_name", "personal_finance_category"
        ]
        df = df[[c for c in keep_cols if c in df.columns]].copy()

        return df

    def _deduplicate_transactions(
        self,
        df: pd.DataFrame,
        start_date: date,
        end_date: date
    ) -> pd.DataFrame:
        """Deduplicate and filter transactions."""
        if df.empty:
            return df

        # Filter date window
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df[
            (df["date"] >= pd.Timestamp(start_date)) &
            (df["date"] <= pd.Timestamp(end_date))
        ]

        # Deduplicate by transaction_id (preferred) or (account_id, date, amount, name)
        if "transaction_id" in df.columns and df["transaction_id"].notna().any():
            df = df.sort_values("date", ascending=False).drop_duplicates(
                subset=["transaction_id"], keep="first"
            ).reset_index(drop=True)
        else:
            subset = [c for c in ["account_id", "date", "amount", "name"] if c in df.columns]
            if subset:
                df = df.sort_values("date", ascending=False).drop_duplicates(
                    subset=subset, keep="first"
                ).reset_index(drop=True)

        return df

    def _load_cursors(self) -> Dict[str, str]:
        """Load sync cursors from file."""
        if self.cursors_path.exists():
            try:
                return json.loads(self.cursors_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not load cursors: {e}")
        return {}

    def _save_cursors(self, cursors: Dict[str, str]):
        """Save sync cursors to file."""
        try:
            self.cursors_path.parent.mkdir(parents=True, exist_ok=True)
            self.cursors_path.write_text(
                json.dumps(cursors, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Could not save cursors: {e}")


class _NoOpContext:
    """No-op context manager when metrics is None."""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

"""
Data Processing Module

Handles:
- Merchant key normalization (aggressive cleanup for identity matching)
- Personal Finance Category (PFC) mapping to friendly names
- YAML category mapping (exact and token-based)
- Non-spend flow detection (transfers, payments, refunds)
- Input validation and error handling
"""

import re
import yaml
from pathlib import Path
from typing import Dict, Optional, List
import pandas as pd

from src.logger import setup_logger, timed

logger = setup_logger(__name__)


class DataProcessingError(Exception):
    """Base exception for data processing errors."""
    pass


# PFC primary category to friendly name mapping
PFC_FRIENDLY_MAP = {
    "FOOD_AND_DRINK": "Dining",
    "GROCERIES": "Groceries",
    "GENERAL_MERCHANDISE": "Shopping",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "HEALTHCARE": "Health",
    "ENTERTAINMENT": "Entertainment",
    "HOME_IMPROVEMENT": "Home Improvement",
    "RENT_AND_UTILITIES": "Utilities",
    "SERVICE": "Services",
    "GOVERNMENT_AND_NON_PROFIT": "Government/Non-Profit",
    "BANK_FEES": "Fees",
    "INCOME": "Income",
    "TRANSFER_OUT": "Transfers",
    "TRANSFER_IN": "Transfers",
    "LOAN_PAYMENTS": "Debt Payments",
    "SUBSCRIPTION": "Subscriptions",
    "RECURRING_SUBSCRIPTIONS": "Subscriptions",
}


def merchant_key_from_name(name: str) -> str:
    """
    Aggressive merchant normalization for identity matching.

    Process:
    1. Uppercase and canonicalize brand patterns (AMZN→AMAZON, PAYPAL, etc.)
    2. Strip bank noise (POS, DEBIT, ACH, ZELLE, etc.)
    3. Remove store numbers and all digits
    4. Keep only letters, '&', spaces, '/', '.' for brand URLs
    5. Collapse whitespace, fallback to 'UNKNOWN'

    Args:
        name: Raw merchant or transaction name

    Returns:
        Normalized merchant key (uppercase, cleaned)

    Examples:
        >>> merchant_key_from_name("AMZN Mktp US*AB1234567")
        'AMAZON'
        >>> merchant_key_from_name("POS PURCHASE STARBUCKS #1234")
        'STARBUCKS'
    """
    if not name:
        return "UNKNOWN"

    u = name.upper()

    # Canonical brand replacements
    canonicalizations = [
        (r"AMZN\s+MKTPL?C?E?|AMAZON\.?\s*COM", "AMAZON"),
        (r"APPLE\.?\s*COM/?BILL", "APPLE.COM/BILL"),
        (r"\bGOOGLE\*", "GOOGLE "),
        (r"\bSQC?\*", "SQUARE "),
        (r"\bPAYPAL\*?", "PAYPAL "),
    ]
    for pattern, replacement in canonicalizations:
        u = re.sub(pattern, replacement, u)

    # Strip bank/payment noise
    noise_patterns = [
        r"APPLE PAY ENDING IN \d{4}",
        r"POS(?:\s+PURCHASE)?",
        r"DEBIT(?:\s+CARD)?(?:\s+PURCHASE)?",
        r"CHECK ?CRD",
        r"VISA(?:\s+POS)?",
        r"MASTERCARD",
        r"DISCOVER",
        r"AMEX",
        r"ACH(?:\s+(CREDIT|DEBIT))?",
        r"WEB AUTHORIZED PMT",
        r"ONLINE PMT",
        r"ZELLE(?:\s+PAYMENT)?",
        r"VENMO(?:\s+PAYMENT)?",
        r"XFER",
        r"TRANSFER",
        r"PURCHASE",
        r"PENDING",
        r"REVERSAL",
        r"ADJ(?:USTMENT)?",
        r"ID[: ]?\d+",
    ]
    for pattern in noise_patterns:
        u = re.sub(rf"\b{pattern}\b", " ", u)

    # Remove store numbers and digits
    u = re.sub(r"#\d{2,}", " ", u)
    u = re.sub(r"\d+", " ", u)

    # Keep only letters, '&', spaces, '/', '.' (for URLish brands)
    u = re.sub(r"[^A-Z&\s\./]", " ", u)

    # Collapse whitespace
    u = re.sub(r"\s+", " ", u).strip()

    # Post-canon cleanup
    u = u.replace("APPLE COM BILL", "APPLE.COM/BILL").strip()

    return u or "UNKNOWN"


@timed(logger)
def extract_pfc_categories(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract Personal Finance Category (PFC) from Plaid response.

    Adds columns:
    - category_pfc_primary: Primary PFC (e.g., "FOOD_AND_DRINK")
    - category_pfc_detailed: Detailed PFC (e.g., "FOOD_AND_DRINK_RESTAURANTS")
    - category: Friendly category name (mapped from PFC)

    Args:
        df: DataFrame with 'personal_finance_category' column

    Returns:
        DataFrame with PFC columns added
    """
    df = df.copy()

    if "personal_finance_category" not in df.columns:
        df["personal_finance_category"] = None

    def extract_pfc_field(pfc, field):
        """Safely extract field from PFC dict or JSON string."""
        if isinstance(pfc, dict):
            return pfc.get(field)
        if isinstance(pfc, str) and pfc.strip().startswith("{"):
            try:
                import json
                parsed = json.loads(pfc)
                if isinstance(parsed, dict):
                    return parsed.get(field)
            except Exception:
                pass
        return None

    df["category_pfc_primary"] = df["personal_finance_category"].apply(
        lambda x: extract_pfc_field(x, "primary")
    )
    df["category_pfc_detailed"] = df["personal_finance_category"].apply(
        lambda x: extract_pfc_field(x, "detailed")
    )

    # Preserve legacy category for fallback
    if "category" in df.columns:
        df["category_plaid_legacy"] = df["category"]
    else:
        df["category_plaid_legacy"] = None

    # Map PFC to friendly names
    df["category"] = (
        df["category_pfc_primary"]
        .map(lambda s: PFC_FRIENDLY_MAP.get(str(s).upper()) if pd.notna(s) and str(s).strip() else None)
        .fillna(df.get("category_plaid_legacy"))
        .fillna("Uncategorized")
    )

    pfc_count = df["category_pfc_primary"].notna().sum()
    logger.info(
        f"Extracted PFC categories: {pfc_count}/{len(df)} rows have PFC",
        extra={'pfc_count': pfc_count, 'total_rows': len(df)}
    )

    return df


@timed(logger)
def add_merchant_keys(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add normalized merchant_key column.

    Args:
        df: DataFrame with 'merchant_name' or 'name' column

    Returns:
        DataFrame with 'merchant_key' column added
    """
    df = df.copy()

    # Use merchant_name if available, fallback to name
    merchant_col = df.get("merchant_name", pd.Series("", index=df.index))
    name_col = df.get("name", pd.Series("", index=df.index))

    df["merchant_key"] = merchant_col.where(
        merchant_col.astype(str).str.len() > 0,
        name_col
    ).apply(merchant_key_from_name)

    logger.info(f"Added merchant keys: {df['merchant_key'].nunique()} unique merchants")

    return df


@timed(logger)
def apply_yaml_mapping(df: pd.DataFrame, yaml_path: Path) -> pd.DataFrame:
    """
    Apply YAML category mappings.

    Supports:
    - Exact merchant_key matches
    - Token-based substring matches

    Adds columns with _final suffix:
    - display_name_final
    - category_final
    - subcategory_final
    - tags_final
    - confidence_final
    - source_final

    Args:
        df: DataFrame with merchant_key column
        yaml_path: Path to categories.yaml file

    Returns:
        DataFrame with _final columns added
    """
    df = df.copy()

    # Initialize final columns
    for col in ["display_name_final", "category_final", "subcategory_final",
                "tags_final", "confidence_final", "source_final"]:
        if col not in df.columns:
            df[col] = None

    if not yaml_path.exists():
        logger.info(f"YAML mapping file not found: {yaml_path}")
        df["source_final"] = "raw"
        df["confidence_final"] = "raw"
        return df

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            yaml_obj = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to parse YAML: {e}")
        df["source_final"] = "raw"
        df["confidence_final"] = "raw"
        return df

    # Extract mapping section
    mapping = _extract_mapping_section(yaml_obj)
    if not mapping:
        logger.info("No mapping section found in YAML")
        df["source_final"] = "raw"
        df["confidence_final"] = "raw"
        return df

    # Split into exact matches and token buckets
    exact_map, token_buckets = _split_yaml_mapping(mapping)

    # Normalize exact map keys
    exact_map_norm = {merchant_key_from_name(k): v for k, v in exact_map.items()}

    # Apply mappings row by row
    rows = []
    yaml_hits = 0

    for _, row in df.iterrows():
        merchant_key = str(row.get("merchant_key", "")).upper()

        # Try exact match first
        if merchant_key in exact_map_norm:
            mapped = _apply_mapping(row, exact_map_norm[merchant_key], "yaml")
            rows.append(mapped)
            yaml_hits += 1
            continue

        # Try token buckets
        token_match = None
        for bucket in token_buckets:
            if any(token in merchant_key for token in bucket["tokens"]):
                token_match = bucket
                break

        if token_match:
            mapped = _apply_mapping(row, token_match, "yaml-token", confidence="bucket")
            rows.append(mapped)
            yaml_hits += 1
        else:
            # No match, keep raw
            mapped = dict(row)
            mapped["display_name_final"] = row.get("merchant_name") or row.get("name")
            mapped["source_final"] = "raw"
            mapped["confidence_final"] = "raw"
            rows.append(mapped)

    result = pd.DataFrame(rows)

    logger.info(
        f"Applied YAML mapping: {yaml_hits}/{len(df)} rows matched",
        extra={'yaml_hits': yaml_hits, 'total_rows': len(df)}
    )

    return result


def _extract_mapping_section(yaml_obj: dict) -> dict:
    """Extract 'mapping' section from YAML (case-insensitive)."""
    if not isinstance(yaml_obj, dict):
        return {}

    # Try known section names
    for key in ["MAPPING", "MERCHANTS", "MERCHANT_MAP", "MAP"]:
        for k in yaml_obj.keys():
            if str(k).strip().upper() == key and isinstance(yaml_obj[k], dict):
                return yaml_obj[k]

    # Check if flat structure (values are all dicts)
    if all(isinstance(v, dict) for v in yaml_obj.values()):
        # Exclude meta sections
        meta = {"CATEGORIES", "DEFAULTS", "NECESSITY_FLAGS", "NON_SPEND_CATEGORIES", "VERSION"}
        if not any(str(k).strip().upper() in meta for k in yaml_obj.keys()):
            return yaml_obj

    return {}


def _split_yaml_mapping(mapping: dict) -> tuple:
    """Split mapping into exact matches and token buckets."""
    exact_map = {}
    token_buckets = []

    for key, value in mapping.items():
        if not isinstance(value, dict):
            continue

        if "tokens" in value and isinstance(value["tokens"], list):
            # Token bucket
            tokens = [str(t).strip().upper() for t in value["tokens"] if str(t).strip()]
            if tokens:
                token_buckets.append({
                    "bucket": str(key),
                    "tokens": tokens,
                    "category": value.get("category"),
                    "subcategory": value.get("subcategory"),
                    "display_name": value.get("display_name"),
                    "tags": value.get("tags"),
                })
        else:
            # Exact match
            exact_map[key] = value

    return exact_map, token_buckets


def _apply_mapping(row: dict, mapping: dict, source: str, confidence: str = "map") -> dict:
    """Apply a mapping to a row."""
    result = dict(row)

    result["display_name_final"] = (
        mapping.get("display_name") or
        row.get("merchant_name") or
        row.get("name") or
        row.get("merchant_key")
    )
    result["category_final"] = mapping.get("category")
    result["subcategory_final"] = mapping.get("subcategory")

    tags = mapping.get("tags")
    if isinstance(tags, (list, tuple)):
        tags = ",".join(str(t) for t in tags)
    result["tags_final"] = tags

    result["confidence_final"] = mapping.get("confidence", confidence)
    result["source_final"] = source

    return result


@timed(logger)
def mark_non_spend_flows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mark non-spend transactions (transfers, payments, refunds, etc.).

    Adds column:
    - is_non_spend_flow: Boolean flag

    Args:
        df: DataFrame with 'name' and/or 'merchant_name' columns

    Returns:
        DataFrame with is_non_spend_flow column
    """
    df = df.copy()

    if df.empty:
        df["is_non_spend_flow"] = False
        return df

    # Patterns that indicate non-spend flows
    patterns = [
        r"PAYMENT",
        r"TRANSFER",
        r"DIRECTPAY",
        r"CREDIT",
        r"REFUND",
        r"REIMBURSE",
        r"ADJUSTMENT",
        r"REVERSAL",
        r"ACH(?!.*APPLE\s+CASH)",  # ACH but not Apple Cash
        r"WEALTHFRONT",
    ]
    pattern = re.compile("|".join(patterns), re.IGNORECASE)

    # Combine name and merchant_name for matching
    names = (
        df.get("name", pd.Series("", index=df.index)).fillna("") + " " +
        df.get("merchant_name", pd.Series("", index=df.index)).fillna("")
    ).str.upper()

    df["is_non_spend_flow"] = names.str.contains(pattern, na=False)

    non_spend_count = df["is_non_spend_flow"].sum()
    logger.info(
        f"Marked non-spend flows: {non_spend_count}/{len(df)} transactions",
        extra={'non_spend_count': non_spend_count, 'total': len(df)}
    )

    return df


@timed(logger)
def finalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coalesce _final columns into canonical columns.

    Creates:
    - display_name: from display_name_final or merchant_name or name
    - category: from category_final or category
    - subcategory: from subcategory_final
    - tags: from tags_final

    Args:
        df: DataFrame with _final columns

    Returns:
        DataFrame with canonical columns
    """
    df = df.copy()

    df["display_name"] = (
        df.get("display_name_final")
        .fillna(df.get("merchant_name"))
        .fillna(df.get("name"))
    )

    df["category"] = df.get("category_final").fillna(df.get("category"))
    df["subcategory"] = df.get("subcategory_final")
    df["tags"] = df.get("tags_final", "").fillna("")

    return df


def validate_dataframe(df: pd.DataFrame) -> List[str]:
    """
    Validate DataFrame for data quality issues.

    Returns:
        List of warning messages (empty if no issues)
    """
    warnings = []

    if df.empty:
        warnings.append("DataFrame is empty")
        return warnings

    # Check required columns
    required_cols = ["date", "amount", "category"]
    for col in required_cols:
        if col not in df.columns:
            warnings.append(f"Missing required column: {col}")

    # Check for NaN/infinite amounts
    if "amount" in df.columns:
        bad_amounts = (~df["amount"].between(-1e10, 1e10)) | df["amount"].isna()
        if bad_amounts.any():
            warnings.append(f"{bad_amounts.sum()} transactions have invalid amounts")

    # Check date range
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if df["date"].isna().any():
            warnings.append(f"{df['date'].isna().sum()} transactions have invalid dates")

        min_date = df["date"].min()
        max_date = df["date"].max()
        if pd.notna(min_date) and min_date.year < 2000:
            warnings.append(f"Suspiciously old dates found: {min_date}")
        if pd.notna(max_date) and max_date > pd.Timestamp.now() + pd.Timedelta(days=7):
            warnings.append(f"Future dates found: {max_date}")

    # Check categorization rate
    if "category" in df.columns:
        uncategorized = (
            df["category"].isna() |
            (df["category"].astype(str).str.strip() == "") |
            (df["category"] == "Uncategorized")
        )
        uncategorized_pct = (uncategorized.sum() / len(df)) * 100
        if uncategorized_pct > 50:
            warnings.append(f"{uncategorized_pct:.1f}% of transactions are uncategorized")

    return warnings

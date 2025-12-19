"""
Unit tests for data processing module.
"""

import pytest
import pandas as pd
from pathlib import Path
from src.data_processing import (
    merchant_key_from_name,
    extract_pfc_categories,
    add_merchant_keys,
    mark_non_spend_flows,
    validate_dataframe,
    PFC_FRIENDLY_MAP
)


class TestMerchantKeyNormalization:
    """Test merchant_key_from_name function."""

    def test_amazon_variations(self):
        """Test Amazon brand normalization."""
        assert merchant_key_from_name("AMZN Mktp US*AB1234567") == "AMAZON"
        assert merchant_key_from_name("AMAZON.COM*1B3C5D7E9") == "AMAZON"
        assert merchant_key_from_name("AMAZON MKTPLACE PMTS") == "AMAZON"

    def test_apple_normalization(self):
        """Test Apple brand normalization."""
        assert merchant_key_from_name("APPLE.COM/BILL") == "APPLE.COM/BILL"
        assert merchant_key_from_name("APPLE COM BILL") == "APPLE.COM/BILL"

    def test_remove_pos_prefix(self):
        """Test POS removal."""
        assert "POS" not in merchant_key_from_name("POS PURCHASE STARBUCKS #1234")
        assert "STARBUCKS" in merchant_key_from_name("POS PURCHASE STARBUCKS #1234")

    def test_remove_store_numbers(self):
        """Test store number removal."""
        key = merchant_key_from_name("WALMART SUPERCENTER #5678")
        assert "#" not in key
        assert "5678" not in key
        assert "WALMART" in key

    def test_remove_digits(self):
        """Test digit removal."""
        key = merchant_key_from_name("TARGET 12345")
        assert "12345" not in key
        assert "TARGET" in key

    def test_empty_string(self):
        """Test empty string handling."""
        assert merchant_key_from_name("") == "UNKNOWN"
        assert merchant_key_from_name(None) == "UNKNOWN"

    def test_uppercase_conversion(self):
        """Test uppercase conversion."""
        assert merchant_key_from_name("Starbucks") == "STARBUCKS"
        assert merchant_key_from_name("starbucks") == "STARBUCKS"


class TestPFCExtraction:
    """Test Personal Finance Category extraction."""

    def test_pfc_extraction_from_dict(self):
        """Test extracting PFC from dict."""
        df = pd.DataFrame([
            {
                'name': 'Test',
                'amount': 10.0,
                'personal_finance_category': {
                    'primary': 'FOOD_AND_DRINK',
                    'detailed': 'FOOD_AND_DRINK_RESTAURANTS'
                }
            }
        ])

        result = extract_pfc_categories(df)

        assert result['category_pfc_primary'].iloc[0] == 'FOOD_AND_DRINK'
        assert result['category_pfc_detailed'].iloc[0] == 'FOOD_AND_DRINK_RESTAURANTS'
        assert result['category'].iloc[0] == 'Dining'

    def test_pfc_missing(self):
        """Test handling missing PFC."""
        df = pd.DataFrame([
            {'name': 'Test', 'amount': 10.0}
        ])

        result = extract_pfc_categories(df)

        assert 'category_pfc_primary' in result.columns
        assert pd.isna(result['category_pfc_primary'].iloc[0])
        assert result['category'].iloc[0] == 'Uncategorized'

    def test_pfc_friendly_mapping(self):
        """Test PFC to friendly name mapping."""
        test_cases = [
            ('FOOD_AND_DRINK', 'Dining'),
            ('GROCERIES', 'Groceries'),
            ('GENERAL_MERCHANDISE', 'Shopping'),
            ('TRANSFER_IN', 'Transfers'),
            ('LOAN_PAYMENTS', 'Debt Payments'),
        ]

        for pfc, expected in test_cases:
            df = pd.DataFrame([{
                'personal_finance_category': {'primary': pfc}
            }])
            result = extract_pfc_categories(df)
            assert result['category'].iloc[0] == expected


class TestMerchantKeys:
    """Test merchant key addition."""

    def test_add_merchant_keys_from_merchant_name(self):
        """Test adding merchant keys from merchant_name."""
        df = pd.DataFrame([
            {'merchant_name': 'Starbucks #1234', 'name': 'Coffee Shop'}
        ])

        result = add_merchant_keys(df)

        assert 'merchant_key' in result.columns
        assert 'STARBUCKS' in result['merchant_key'].iloc[0]
        assert '1234' not in result['merchant_key'].iloc[0]

    def test_fallback_to_name(self):
        """Test fallback to name when merchant_name is empty."""
        df = pd.DataFrame([
            {'merchant_name': '', 'name': 'TARGET'}
        ])

        result = add_merchant_keys(df)

        assert 'TARGET' in result['merchant_key'].iloc[0]


class TestNonSpendFlows:
    """Test non-spend flow detection."""

    def test_mark_payments(self):
        """Test payment detection."""
        df = pd.DataFrame([
            {'name': 'PAYMENT - THANK YOU', 'merchant_name': ''},
            {'name': 'Regular Purchase', 'merchant_name': 'Store'},
        ])

        result = mark_non_spend_flows(df)

        assert result['is_non_spend_flow'].iloc[0] == True
        assert result['is_non_spend_flow'].iloc[1] == False

    def test_mark_transfers(self):
        """Test transfer detection."""
        df = pd.DataFrame([
            {'name': 'TRANSFER TO SAVINGS', 'merchant_name': ''},
            {'name': 'ACH TRANSFER', 'merchant_name': ''},
        ])

        result = mark_non_spend_flows(df)

        assert result['is_non_spend_flow'].iloc[0] == True
        assert result['is_non_spend_flow'].iloc[1] == True

    def test_mark_refunds(self):
        """Test refund detection."""
        df = pd.DataFrame([
            {'name': 'REFUND - RETURN', 'merchant_name': ''},
        ])

        result = mark_non_spend_flows(df)

        assert result['is_non_spend_flow'].iloc[0] == True


class TestDataValidation:
    """Test data validation."""

    def test_empty_dataframe(self):
        """Test validation of empty DataFrame."""
        df = pd.DataFrame()
        warnings = validate_dataframe(df)

        assert len(warnings) > 0
        assert any('empty' in w.lower() for w in warnings)

    def test_missing_required_columns(self):
        """Test detection of missing columns."""
        df = pd.DataFrame([{'foo': 'bar'}])
        warnings = validate_dataframe(df)

        assert any('date' in w.lower() for w in warnings)
        assert any('amount' in w.lower() for w in warnings)

    def test_invalid_amounts(self):
        """Test detection of invalid amounts."""
        df = pd.DataFrame([
            {'date': '2024-01-01', 'amount': float('inf'), 'category': 'Test'},
            {'date': '2024-01-02', 'amount': None, 'category': 'Test'},
        ])

        warnings = validate_dataframe(df)

        assert any('invalid amounts' in w.lower() for w in warnings)

    def test_future_dates(self):
        """Test detection of future dates."""
        future_date = pd.Timestamp.now() + pd.Timedelta(days=30)
        df = pd.DataFrame([
            {'date': future_date, 'amount': 10.0, 'category': 'Test'}
        ])

        warnings = validate_dataframe(df)

        assert any('future' in w.lower() for w in warnings)

    def test_high_uncategorized_rate(self):
        """Test detection of high uncategorized rate."""
        df = pd.DataFrame([
            {'date': '2024-01-01', 'amount': 10.0, 'category': 'Uncategorized'},
            {'date': '2024-01-02', 'amount': 20.0, 'category': 'Uncategorized'},
            {'date': '2024-01-03', 'amount': 30.0, 'category': 'Dining'},
        ])

        warnings = validate_dataframe(df)

        assert any('uncategorized' in w.lower() for w in warnings)

    def test_valid_dataframe_no_warnings(self):
        """Test that valid DataFrame produces no warnings."""
        df = pd.DataFrame([
            {'date': '2024-01-01', 'amount': 10.0, 'category': 'Dining'},
            {'date': '2024-01-02', 'amount': 20.0, 'category': 'Shopping'},
            {'date': '2024-01-03', 'amount': 30.0, 'category': 'Transportation'},
        ])

        warnings = validate_dataframe(df)

        assert len(warnings) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

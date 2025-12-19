"""
Configuration Module

Handles:
- Environment variable loading and validation
- Path resolution (CI-safe, works from any directory)
- Access token parsing (multiple formats: JSON, pairs, CSV)
- Plaid client configuration
- Security: masks sensitive data in logs
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass

from src.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class PlaidConfig:
    """Plaid API configuration."""
    client_id: str
    secret: str
    environment: str  # production, development, or sandbox
    access_tokens: Dict[str, str]  # bank_name -> access_token

    def validate(self):
        """Validate configuration."""
        errors = []

        if not self.client_id:
            errors.append("PLAID_CLIENT_ID is missing")

        if not self.secret:
            errors.append("PLAID_SECRET is missing")

        if self.environment not in {'production', 'development', 'sandbox'}:
            errors.append(f"Invalid PLAID_ENV: {self.environment}")

        if not self.access_tokens:
            errors.append("No access tokens found")

        # Validate token format
        expected_prefix = f"access-{self.environment}-"
        pattern = re.compile(r"^access-(?:production|development|sandbox)-[a-z0-9\-]+$")

        for bank, token in self.access_tokens.items():
            if not isinstance(token, str):
                errors.append(f"Token for {bank} is not a string")
            elif not token.startswith(expected_prefix):
                errors.append(f"Token for {bank} doesn't match environment {self.environment}")
            elif not pattern.match(token):
                errors.append(f"Token for {bank} has invalid format (must be canonical, no '/', '+', '=')")

        if errors:
            raise ValueError(f"Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI configuration."""
    endpoint: str
    api_key: str
    deployment: str  # Chat model deployment (e.g., gpt-4o-mini)
    embeddings_deployment: Optional[str] = None
    api_version: str = "2024-02-15-preview"

    def validate(self):
        """Validate configuration."""
        errors = []

        if not self.endpoint:
            errors.append("AZURE_OPENAI_ENDPOINT is missing")

        if not self.api_key:
            errors.append("AZURE_OPENAI_API_KEY is missing")

        if not self.deployment:
            errors.append("AZURE_OPENAI_DEPLOYMENT is missing")

        if errors:
            raise ValueError(f"Azure OpenAI configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class EmailConfig:
    """Email configuration for SMTP."""
    enabled: bool = False
    dry_run: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_ssl_port: int = 465
    use_starttls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    to_addresses: List[str] = None
    cc_addresses: List[str] = None
    bcc_addresses: List[str] = None

    def __post_init__(self):
        if self.to_addresses is None:
            self.to_addresses = []
        if self.cc_addresses is None:
            self.cc_addresses = []
        if self.bcc_addresses is None:
            self.bcc_addresses = []


class Config:
    """
    Main configuration class for the financial dashboard.

    Handles loading, validation, and access to all configuration.
    """

    def __init__(self, load_dotenv: bool = True):
        """
        Initialize configuration.

        Args:
            load_dotenv: If True, load .env files
        """
        if load_dotenv:
            self._load_env_files()

        self.repo_root = self._find_repo_root()
        self._setup_paths()

        # Load configurations
        self.plaid = self._load_plaid_config()
        self.azure_openai = self._load_azure_openai_config()
        self.email = self._load_email_config()

        # Processing parameters
        self.days_back = int(os.getenv("DAYS_BACK", "180"))
        self.goal_savings = float(os.getenv("GOAL_SAVINGS", "1000.0"))
        self.anomaly_z_threshold = float(os.getenv("ANOMALY_Z", "2.5"))
        self.precheck = os.getenv("PRECHECK", "0") == "1"
        self.force_full_resync = os.getenv("FORCE_FULL_RESYNC", "0").lower() in {"1", "true", "yes", "on"}

        logger.info("Configuration loaded", extra={
            'repo_root': str(self.repo_root),
            'environment': self.plaid.environment,
            'days_back': self.days_back,
        })

    def _load_env_files(self):
        """Load environment variables from .env files."""
        try:
            from dotenv import load_dotenv, find_dotenv

            # Try multiple locations
            env_paths = [
                os.getenv("ENV_PATH"),
                "scripts/.env",
                ".env",
                "config/.env",
            ]

            for path in env_paths:
                if path and Path(path).exists():
                    try:
                        load_dotenv(str(path), override=False, encoding="utf-8")
                        logger.debug(f"Loaded .env from {path}")
                    except TypeError:
                        # Older dotenv versions don't support encoding parameter
                        load_dotenv(str(path), override=False)
                        logger.debug(f"Loaded .env from {path}")

            # Also try find_dotenv as fallback
            found = find_dotenv(usecwd=True)
            if found:
                try:
                    load_dotenv(found, override=False, encoding="utf-8")
                except TypeError:
                    load_dotenv(found, override=False)

        except ImportError:
            logger.warning("python-dotenv not installed, skipping .env file loading")

    def _find_repo_root(self) -> Path:
        """Find the repository root directory."""
        # Check GitHub Actions workspace first
        gw = os.getenv("GITHUB_WORKSPACE")
        if gw:
            root = Path(gw).resolve()
            logger.debug(f"Using GITHUB_WORKSPACE: {root}")
            return root

        # Search for .git or spending-dashboard directory
        cwd = Path.cwd().resolve()
        for path in [cwd, *cwd.parents]:
            if (path / ".git").exists() or path.name == "spending-dashboard":
                logger.debug(f"Found repo root: {path}")
                return path

        logger.warning(f"Could not find repo root, using cwd: {cwd}")
        return cwd

    def _setup_paths(self):
        """Set up directory paths."""
        self.output_dir = Path(os.getenv("OUTPUT_DIR", str(self.repo_root / "data" / "raw")))
        self.processed_dir = self.repo_root / "data" / "processed"
        self.insights_dir = self.processed_dir / "insights"
        self.state_dir = Path(os.getenv("STATE_DIR", str(self.repo_root / ".state")))
        self.config_dir = self.repo_root / "config"

        # Create directories
        for dir_path in [self.output_dir, self.processed_dir, self.insights_dir,
                         self.state_dir, self.config_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Important file paths
        self.tokens_path = Path(os.getenv("TOKENS_PATH", str(self.state_dir / "access_tokens.json")))
        self.cursors_path = self.state_dir / "plaid_cursors.json"
        self.latest_csv_path = self.output_dir / "latest.csv"
        self.enriched_csv_path = self.processed_dir / "latest_enriched.csv"
        self.merchants_dim_path = self.config_dir / "merchants_dim.csv"
        self.categories_yaml_path = self.config_dir / "categories.yaml"
        self.email_kill_path = self.state_dir / "EMAIL_KILL"

    def _load_plaid_config(self) -> PlaidConfig:
        """Load and validate Plaid configuration."""
        client_id = os.getenv("PLAID_CLIENT_ID", "")
        secret = os.getenv("PLAID_SECRET", "")

        # Normalize environment
        env = (os.getenv("PLAID_ENV", "production") or "production").strip().lower()
        env_aliases = {
            "prod": "production",
            "live": "production",
            "dev": "development",
            "devel": "development",
            "sb": "sandbox"
        }
        env = env_aliases.get(env, env)
        if env not in {"production", "development", "sandbox"}:
            env = "production"

        # Load access tokens
        access_tokens = self._load_access_tokens()

        config = PlaidConfig(
            client_id=client_id,
            secret=secret,
            environment=env,
            access_tokens=access_tokens
        )

        config.validate()
        return config

    def _load_access_tokens(self) -> Dict[str, str]:
        """
        Load and parse Plaid access tokens from environment or file.

        Supports multiple formats:
        - JSON: {"Bank1": "access-production-...", "Bank2": "..."}
        - Pairs: "Bank1=access-production-...\nBank2=..."
        - CSV: "Bank1,access-production-...\nBank2,..."
        """
        # Try environment variable first
        blob = os.getenv("PLAID_ACCESS_TOKENS", "").strip()
        if blob:
            tokens = self._parse_tokens(blob)
            if tokens:
                logger.info(f"Loaded {len(tokens)} access tokens from environment")
                return tokens

        # Try tokens file
        if self.tokens_path.exists():
            try:
                raw = self.tokens_path.read_text(encoding="utf-8", errors="ignore")
                tokens = self._parse_tokens(raw)
                if tokens:
                    logger.info(f"Loaded {len(tokens)} access tokens from {self.tokens_path}")
                    return tokens
            except Exception as e:
                logger.error(f"Failed to read tokens file: {e}")

        raise ValueError(
            f"Could not load access tokens. Provide PLAID_ACCESS_TOKENS environment variable "
            f"or a valid JSON file at {self.tokens_path}"
        )

    def _parse_tokens(self, blob: str) -> Dict[str, str]:
        """Parse tokens from various formats."""
        # Strip BOM
        blob = blob.lstrip("\ufeff").strip()
        if not blob:
            return {}

        # Try JSON first
        try:
            parsed = json.loads(blob)
            return self._normalize_tokens(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try key=value pairs
        return self._parse_pairs_blob(blob)

    def _parse_pairs_blob(self, blob: str) -> Dict[str, str]:
        """Parse tokens from key=value or key:value pairs."""
        # Split by newline, semicolon, pipe, or comma
        raw = []
        for sep in ["\n", ";", "|", ","]:
            if sep in blob:
                raw = [p.strip() for p in blob.split(sep) if p.strip()]
                break

        if not raw:
            raw = [blob.strip()]

        tokens = {}
        for pair in raw:
            if "=" in pair:
                key, value = pair.split("=", 1)
            elif ":" in pair:
                key, value = pair.split(":", 1)
            else:
                continue

            key = key.strip().strip('"').strip("'")
            value = value.strip().strip('"').strip("'")

            if key and value:
                tokens[key] = value

        return tokens

    def _normalize_tokens(self, obj) -> Dict[str, str]:
        """Normalize tokens from various structures."""
        if isinstance(obj, dict):
            return {str(k): str(v).strip() for k, v in obj.items()}

        if isinstance(obj, list):
            tokens = {}
            for item in obj:
                if isinstance(item, dict):
                    name = item.get("issuer") or item.get("bank") or item.get("name")
                    token = item.get("access_token") or item.get("token")
                    if name and token:
                        tokens[str(name)] = str(token).strip()
            return tokens

        return {}

    def _load_azure_openai_config(self) -> Optional[AzureOpenAIConfig]:
        """Load Azure OpenAI configuration (optional)."""
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        embeddings = os.getenv("AZURE_OPENAI_EMBEDDINGS", "")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        if not (endpoint and api_key and deployment):
            logger.info("Azure OpenAI not configured (optional)")
            return None

        config = AzureOpenAIConfig(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            embeddings_deployment=embeddings if embeddings else None,
            api_version=api_version
        )

        config.validate()
        logger.info("Azure OpenAI configured", extra={'deployment': deployment})
        return config

    def _load_email_config(self) -> EmailConfig:
        """Load email configuration (optional)."""
        enabled = os.getenv("EMAIL_ENABLED", "0") == "1"
        dry_run = os.getenv("EMAIL_DRY_RUN", "1") == "1"

        # Check for kill switch
        if self.email_kill_path.exists():
            logger.warning("EMAIL_KILL switch is active, emails will be suppressed")
            enabled = False

        config = EmailConfig(
            enabled=enabled,
            dry_run=dry_run,
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_ssl_port=int(os.getenv("SMTP_SSL_PORT", "465")),
            use_starttls=os.getenv("SMTP_STARTTLS", "1") == "1",
            username=os.getenv("SMTP_USERNAME", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            from_address=os.getenv("EMAIL_FROM", ""),
            to_addresses=[a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()],
            cc_addresses=[a.strip() for a in os.getenv("EMAIL_CC", "").split(",") if a.strip()],
            bcc_addresses=[a.strip() for a in os.getenv("EMAIL_BCC", "").split(",") if a.strip()],
        )

        if enabled and not dry_run:
            logger.info("Email enabled", extra={'from': config.from_address})
        elif dry_run:
            logger.info("Email in dry-run mode (will not send)")
        else:
            logger.info("Email disabled")

        return config


if __name__ == "__main__":
    # Demo usage
    import logging
    logger.setLevel(logging.DEBUG)

    config = Config()
    print(f"Repo root: {config.repo_root}")
    print(f"Plaid environment: {config.plaid.environment}")
    print(f"Access tokens: {len(config.plaid.access_tokens)}")
    print(f"Days back: {config.days_back}")
    print(f"Azure OpenAI: {'configured' if config.azure_openai else 'not configured'}")

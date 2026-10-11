from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # Sarvam
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_chat_model: str = "sarvam-105b"
    doc_language: str = "en-IN"
    doc_poll_interval_s: float = 3.0
    doc_poll_timeout_s: float = 180.0
    sarvam_mode: str = "live"  # "live" | "mock" (offline fixtures, used by tests)

    # Usage guardrails: the API key has limited credits
    sarvam_token_budget: int = 150_000  # total chat tokens (prompt + completion) this deployment may spend
    sarvam_page_budget: int = 40  # total document pages sent to Sarvam Vision
    extract_max_tokens: int = 2500
    explain_max_tokens: int = 400
    max_markdown_chars: int = 12_000  # trim OCR output before sending to the LLM

    # Storage
    database_url: str = f"sqlite:///{BASE_DIR / 'ap_agent.db'}"
    upload_dir: Path = BASE_DIR / "uploads"
    fixtures_dir: Path = BASE_DIR / "seed" / "fixtures"

    # Buyer (our company)
    buyer_name: str = "Acme Retail Pvt Ltd"
    buyer_gstin: str = "27AAACA1234A1ZK"

    # Matching tolerances
    price_tolerance_pct: float = 2.0
    qty_tolerance: float = 0.0
    total_tolerance_abs: float = 100.0
    total_tolerance_pct: float = 1.0
    line_amount_tolerance_abs: float = 1.0

    # Validation / policy
    low_confidence_threshold: float = 0.75
    auto_approve_limit: float = 50_000.0
    single_approver_limit: float = 200_000.0
    msme_max_payment_days: int = 45

    @property
    def mock_mode(self) -> bool:
        return self.sarvam_mode == "mock" or not self.sarvam_api_key


settings = Settings()

"""
app/core/config.py
환경변수 기반 설정 관리 (Pydantic Settings)
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/gonggong"

    # 나라장터 OpenAPI 키 (공공데이터포털에서 발급)
    # 빈 문자열이면 MockG2BFetcher 자동 사용
    G2B_API_KEY: str = ""

    # 매일 자동 수집 시각 (한국 시간 기준, 0~23)
    COLLECT_HOUR: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def use_mock_g2b(self) -> bool:
        """API 키가 없으면 Mock 사용."""
        return not self.G2B_API_KEY.strip()


settings = Settings()

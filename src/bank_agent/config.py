"""全局配置:从 .env 加载,全项目唯一入口。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM(OpenAI 兼容接口,如 DeepSeek)
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""

    # mock 银行核心数据库
    bank_db_path: str = "bank.sqlite3"

    # mock IdP:本地固定密钥签发 JWT(仅开发/教学用,生产应换真 IdP)
    jwt_secret: str = "dev-only-fixed-secret-change-me-in-real-deploy"
    jwt_ttl_seconds: int = 3600

    # MCP Server 地址(Streamable HTTP)
    mcp_accounts_url: str = "http://127.0.0.1:8101/mcp"
    mcp_transactions_url: str = "http://127.0.0.1:8102/mcp"
    mcp_service_url: str = "http://127.0.0.1:8103/mcp"

    # MCP Server 监听端口
    mcp_accounts_port: int = 8101
    mcp_transactions_port: int = 8102
    mcp_service_port: int = 8103

    # FastAPI 服务端口
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""应用配置：从环境变量 / .env 加载，集中管理 API Key 等设置。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


AGENT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = AGENT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "pydantic-ai-agent"
    environment: str = "development"
    # 允许跨域访问的前端来源；"*" 表示放行所有来源（开发环境默认）
    cors_origins: list[str] = ["*"]
    # 大模型 API Key、Base URL 与模型名
    openai_api_key: str | None = None
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen-plus"
    # 单次 LLM 请求超时（秒）与失败重试次数；调小可让慢/挂的接口更快暴露失败
    openai_timeout: float = 30.0
    openai_max_retries: int = 1
    # 安全审核配置保留；当前主 Agent 流程未接入安全审核阶段
    safety_max_retries: int = 0
    # MCP 服务器地址（SSE 传输），客服工具由此服务器提供
    mcp_server_url: str = "http://localhost:8081/sse"

    # —— 多层记忆：本地热数据 + Redis 温数据 + Qdrant 快照/语义召回 + MySQL 最终记录 ——
    # L2 Redis：温数据，跨进程共享，带 TTL
    redis_url: str = "redis://localhost:6379/0"
    redis_protocol: int = 2
    memory_redis_ttl_seconds: int = 604800  # 7 天
    # MySQL：Agent 会话状态与消息流水的最终记录
    mysql_dsn: str = "mysql+aiomysql://root:root@localhost:3307/digital_cs?charset=utf8mb4"
    # Qdrant：会话快照、消息快照与长期语义记忆向量库
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "agent_memory"
    # Embedding：复用 OPENAI_API_KEY + base_url 的 OpenAI 兼容 /embeddings（DashScope）
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024
    # 语义召回 top-k；本地缓存容量；MySQL 回源拉取的最近消息条数
    memory_recall_top_k: int = 2
    memory_recall_min_score: float = 0.85
    memory_local_cache_size: int = 256
    # 短期窗口保留的最近消息条数：最近 3 轮（user/assistant 各一条，共 6 条）
    memory_recent_messages: int = 6


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

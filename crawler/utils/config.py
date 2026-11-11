import os
from pathlib import Path


def load_env():
    """从仓库根目录的 .env 读取本地配置。文件已被 Git 忽略。"""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    values = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


ENV = load_env()

DB_CONFIG = {
    "host": ENV["CRAWL_DB_HOST"],
    "port": int(ENV["CRAWL_DB_PORT"]),
    "user": ENV["CRAWL_DB_USER"],
    "password": ENV["CRAWL_DB_PASSWORD"],
    "database": ENV["CRAWL_DB_NAME"],
    "charset": "utf8mb4",
}

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
PRACTICE_SHOP_URL = os.getenv(
    "PRACTICE_SHOP_URL",
    "http://127.0.0.1:8088/wp-json/wc/store/v1/products",
)

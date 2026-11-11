import redis

from utils.config import REDIS_URL

POOL = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
STREAM = "crawl:orders"
GROUP = "workers"
DEAD_LETTER_STREAM = "crawl:dead-letters"


def client():
    return redis.Redis(connection_pool=POOL)


def ensure_group():
    """消费组只创建一次。已存在时 Redis 返回 BUSYGROUP。"""
    conn = client()
    try:
        conn.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def move_to_dead_letter(message_id, order_id, reason):
    """确认原消息，并把失败原因转移到死信 Stream。"""
    conn = client()
    conn.xadd(DEAD_LETTER_STREAM, {
        "order_id": str(order_id),
        "source_id": message_id,
        "reason": reason[:200],
    })
    conn.xack(STREAM, GROUP, message_id)


def record_heartbeat(worker_name):
    """心跳 30 秒过期。进程崩溃后，键会自动消失。"""
    client().set(f"crawl:worker:{worker_name}", "1", ex=30)


def list_workers():
    conn = client()
    names = []
    for key in conn.scan_iter("crawl:worker:*"):
        names.append(key.removeprefix("crawl:worker:"))
    return sorted(names)


def queue_metrics():
    conn = client()
    ensure_group()
    pending = conn.xpending(STREAM, GROUP)
    return {
        "queued": conn.xlen(STREAM),
        "pending": pending.get("pending", 0),
        "dead": conn.xlen(DEAD_LETTER_STREAM),
    }


def push_order(order_id):
    """把一个订单放进 Redis。消息只保存订单 ID，不保存商品数据。"""
    ensure_group()
    return client().xadd(STREAM, {"order_id": str(order_id)})

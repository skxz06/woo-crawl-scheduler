import logging
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import cache, db
from utils.config import PRACTICE_SHOP_URL

log = logging.getLogger(__name__)
LEASE_MS = 60_000
MAX_ATTEMPTS = 3


def claim_order(worker_name):
    """优先接管超时未确认的订单，再领取新订单。"""
    conn = cache.client()
    _next_id, records, *_rest = conn.xautoclaim(
        cache.STREAM,
        cache.GROUP,
        worker_name,
        min_idle_time=LEASE_MS,
        start_id="0-0",
        count=1,
    )
    if not records:
        records = conn.xreadgroup(
            cache.GROUP,
            worker_name,
            {cache.STREAM: ">"},
            count=1,
            block=5_000,
        )
        if records:
            records = records[0][1]
    if not records:
        return None
    message_id, fields = records[0]
    return message_id, int(fields["order_id"])


class AccessDenied(RuntimeError):
    """目标明确拒绝访问。浏览器不能把拒绝变成一次合法抓取。"""


class ContractBroken(RuntimeError):
    """公开 JSON 契约失效，但同一公开页面仍可能提供商品。"""


def classify_response(response):
    if response.status_code in (401, 403):
        raise AccessDenied(f"access denied: HTTP {response.status_code}")
    if response.status_code == 429:
        raise requests.HTTPError(f"retryable rate limit: HTTP {response.status_code}")
    if response.status_code == 404 or "text/html" in response.headers.get("Content-Type", ""):
        raise ContractBroken(f"JSON contract unavailable: HTTP {response.status_code}")
    response.raise_for_status()


def fetch_products_with_browser(url, count):
    """只读取同一公开页面。浏览器全局只启动一个，不能用于绕过拒绝访问。"""
    from playwright.sync_api import sync_playwright

    shop_url = url.split("/wp-json/", 1)[0] + "/shop/"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto(shop_url, wait_until="networkidle", timeout=30000)
        titles = page.locator(".wp-block-post-title").all_inner_texts()
        prices = page.locator(".wc-block-components-product-price").all_inner_texts()
        browser.close()
    products = []
    for index, title in enumerate(titles[:count], start=1):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", prices[index - 1] if index <= len(prices) else "")
        if not match:
            continue
        products.append({
            "id": f"html-{index}",
            "name": title.strip(),
            "prices": {
                "currency_code": "CNY",
                "currency_minor_unit": 2,
                "price": str(int(float(match.group(1)) * 100)),
            },
            "on_sale": "促销" in (prices[index - 1] if index <= len(prices) else ""),
            "is_in_stock": True,
        })
    return products


def store_api_url(order):
    """订单必须绑定 WooCommerce 店铺地址，不能把任意 URL 当成采集目标。"""
    if order.get("platform", "woocommerce") != "woocommerce":
        raise RuntimeError(f"unsupported platform: {order.get('platform')}")
    return order["url"].rstrip("/") + "/wp-json/wc/store/v1/products"


def fetch_products(order):
    """请求公开 Store API。count 表示最多抓取的页数。"""
    url = store_api_url(order)
    per_page = int(order.get("per_page") or 2)
    response = requests.get(url, params={"per_page": per_page, "page": 1}, timeout=15)
    classify_response(response)
    total_pages = min(int(response.headers["X-WP-TotalPages"]), int(order["count"]))
    products = response.json()
    for page in range(2, total_pages + 1):
        page_response = requests.get(url, params={"per_page": per_page, "page": page}, timeout=15)
        classify_response(page_response)
        products.extend(page_response.json())
    return products


def save_products(order_id, products):
    for product in products:
        prices = product["prices"]
        db.insert(
            """
            INSERT INTO products (
                order_id, external_id, name, currency_code, minor_unit,
                price_minor, regular_price_minor, on_sale, in_stock, fetched_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON DUPLICATE KEY UPDATE
                name=VALUES(name),
                price_minor=VALUES(price_minor),
                regular_price_minor=VALUES(regular_price_minor),
                on_sale=VALUES(on_sale),
                in_stock=VALUES(in_stock),
                fetched_at=NOW()
            """,
            [
                order_id,
                str(product["id"]),
                product["name"],
                prices["currency_code"],
                int(prices["currency_minor_unit"]),
                int(prices["price"]),
                int(prices["regular_price"]) if prices.get("regular_price") else None,
                1 if product["on_sale"] else 0,
                1 if product["is_in_stock"] else 0,
            ],
        )


def record_failure(order_id, terminal=False):
    """记录一次失败。拒绝访问立即失败；其他错误累计到上限后失败。"""
    db.insert("UPDATE `order` SET attempts = attempts + 1 WHERE id=%s", [order_id])
    order = db.fetch_one("SELECT attempts FROM `order` WHERE id=%s", [order_id])
    attempts = order["attempts"]
    if terminal or attempts >= MAX_ATTEMPTS:
        db.insert("UPDATE `order` SET status=4 WHERE id=%s", [order_id])
    return attempts


def process_order(order_id, worker_name):
    order = db.fetch_one(
        "SELECT id, url, count, per_page, platform, status FROM `order` WHERE id=%s",
        [order_id],
    )
    if not order:
        raise RuntimeError(f"order {order_id} does not exist")
    db.insert(
        "UPDATE `order` SET status=2, worker_name=%s WHERE id=%s",
        [worker_name, order_id],
    )
    try:
        products = fetch_products(order)
    except ContractBroken:
        log.warning("order %s JSON contract broken; using one public browser page", order_id)
        products = fetch_products_with_browser(store_api_url(order), order["count"])
    save_products(order_id, products)
    db.insert("UPDATE `order` SET status=3 WHERE id=%s", [order_id])
    log.info("order %s saved %s products", order_id, len(products))


def main():
    logging.basicConfig(level=logging.INFO)
    worker_name = sys.argv[1] if len(sys.argv) > 1 else "worker-1"
    cache.ensure_group()
    log.info("%s started; practice API is %s", worker_name, PRACTICE_SHOP_URL)
    while True:
        cache.record_heartbeat(worker_name)
        claimed = claim_order(worker_name)
        if claimed is None:
            continue
        message_id, order_id = claimed
        try:
            log.info("%s claimed order %s", worker_name, order_id)
            process_order(order_id, worker_name)
            cache.client().xack(cache.STREAM, cache.GROUP, message_id)
        except AccessDenied as exc:
            attempts = record_failure(order_id, terminal=True)
            cache.move_to_dead_letter(message_id, order_id, str(exc))
            log.error("order %s denied; browser fallback skipped", order_id)
        except Exception as exc:
            attempts = record_failure(order_id)
            if attempts >= MAX_ATTEMPTS:
                cache.move_to_dead_letter(message_id, order_id, str(exc))
                log.error("order %s moved to dead letter after %s attempts", order_id, attempts)
            else:
                # 不 ACK。消息留在待确认列表，租约超时后由 Worker 接管。
                log.exception("order %s failed on attempt %s", order_id, attempts)
        time.sleep(0.1)


if __name__ == "__main__":
    main()

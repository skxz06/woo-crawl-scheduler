import csv
import io

from flask import Blueprint, Response, abort, redirect, render_template, request, session
from utils import db,cache
# 蓝图对象
od = Blueprint('order', __name__)
PLATFORMS = {
    "woocommerce": "WooCommerce 公开 Store API",
}
PER_PAGE_OPTIONS = (2, 10, 20)


def format_price(value, minor_unit):
    """把最小货币单位还原成真实金额。"""
    if value is None:
        return ""
    return f"{int(value) / (10 ** int(minor_unit)):.{int(minor_unit)}f}"


def current_user():
    return session.get("user_info")


def owned_order(order_id):
    user = current_user()
    if user["role"] == 2:
        return db.fetch_one("SELECT id, status, user_id FROM `order` WHERE id=%s", [order_id])
    return db.fetch_one(
        "SELECT id, status, user_id FROM `order` WHERE id=%s AND user_id=%s",
        [order_id, user["id"]],
    )

@od.route('/order/list')
def order_list():
    user_info = session.get('user_info')
    role = user_info["role"]
    columns = """
        `order`.id, `order`.platform, `order`.url, `order`.count,
        `order`.per_page, `order`.status, `order`.worker_name, userinfo.real_name
    """
    if role == 2:
        data_list = db.fetch_all(
            f"select {columns} from `order` left join userinfo on `order`.user_id = userinfo.id",
            [],
        )
    else:
        data_list = db.fetch_all(
            f"select {columns} from `order` left join userinfo on `order`.user_id = userinfo.id where `order`.user_id=%s",
            [user_info["id"]],
        )
    status_dict = {
        1:"排队中",
        2:"正在执行",
        3:"完成",
        4:"失败"
    }
    return render_template(
        "order_list.html",
        data_list=data_list,
        status_dict=status_dict,
        workers=cache.list_workers(),
        metrics=cache.queue_metrics(),
    )

@od.route('/order/create', methods=['GET','POST'])
def create_order():
    # 创建订单逻辑
    if request.method == 'GET':
        return render_template("order_create.html", platforms=PLATFORMS, per_page_options=PER_PAGE_OPTIONS)
    platform = request.form.get("platform", "")
    url = request.form.get('url', '').strip().rstrip("/")
    count = request.form.get('count', '').strip()
    per_page = request.form.get("per_page", "")
    valid = (
        platform in PLATFORMS
        and url.startswith(("http://", "https://"))
        and count.isdigit() and 1 <= int(count) <= 20
        and per_page.isdigit() and int(per_page) in PER_PAGE_OPTIONS
    )
    if not valid:
        return render_template(
            "order_create.html",
            error="请选择 WooCommerce 平台、完整店铺地址、1 到 20 页和允许的每页数量",
            platforms=PLATFORMS,
            per_page_options=PER_PAGE_OPTIONS,
        )
    # 先写订单，再把订单 ID 放进 Redis。Worker 根据订单 ID 回表处理。
    user_info = current_user()
    order_id = db.insert(
        "insert into `order`(platform,url,count,per_page,user_id,status) values(%s,%s,%s,%s,%s,1)",
        [platform, url, int(count), int(per_page), user_info['id']],
    )
    cache.push_order(order_id)
    return redirect('/order/list')

@od.post("/order/<int:order_id>/retry")
def retry_order(order_id):
    order = owned_order(order_id)
    if not order:
        abort(404)
    if order["status"] == 2:
        return redirect("/order/list")
    db.execute(
        "UPDATE `order` SET status=1, attempts=0, worker_name=NULL WHERE id=%s",
        [order_id],
    )
    cache.push_order(order_id)
    return redirect("/order/list")


@od.get("/order/export.csv")
def export_orders():
    user = current_user()
    params = []
    where = ""
    if user["role"] != 2:
        where = "WHERE `order`.user_id=%s"
        params.append(user["id"])
    elif request.args.get("user_id", "").isdigit():
        where = "WHERE `order`.user_id=%s"
        params.append(int(request.args["user_id"]))
    rows = db.fetch_all(
        f"""
        SELECT `order`.id, userinfo.real_name, `order`.platform, `order`.url,
               products.external_id, products.name, products.currency_code,
               products.minor_unit, products.price_minor,
               products.regular_price_minor, products.on_sale
        FROM `order`
        JOIN userinfo ON `order`.user_id = userinfo.id
        LEFT JOIN products ON products.order_id = `order`.id
        {where}
        ORDER BY `order`.id, products.id
        """,
        params,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["订单ID", "用户", "平台", "店铺", "商品ID", "商品名称", "币种", "真实价格", "原价", "是否促销"])
    for row in rows:
        minor = row["minor_unit"] if row["minor_unit"] is not None else 2
        writer.writerow([
            row["id"], row["real_name"], row["platform"], row["url"],
            row["external_id"], row["name"], row["currency_code"],
            format_price(row["price_minor"], minor),
            format_price(row["regular_price_minor"], minor),
            "是" if row["on_sale"] else "否",
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )
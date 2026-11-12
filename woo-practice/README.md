# 本地 WooCommerce 店铺

本目录用 Docker Compose 启动一个 WooCommerce 店铺，为采集系统提供公开商品接口。调度服务位于仓库根目录的 `crawler/`，整体说明见根目录 `README.md`。

## 这个接口是什么

练习店使用 WooCommerce 的公开 Store API：

```text
GET /wp-json/wc/store/v1/products?per_page=2&page=1
```

本地完整地址是：

```text
http://127.0.0.1:8088/wp-json/wc/store/v1/products?per_page=2&page=1
```

它返回商品 JSON，不需要登录，也没有签名、时间戳或加密参数。请求里只有两个业务参数：

| 参数 | 作用 | 本练习店的例子 |
| --- | --- | --- |
| `per_page` | 一页返回几条 | `2` |
| `page` | 请求第几页 | `1` 到 `5` |

浏览器打开店铺首页时不一定能在 Network 里看到这个请求。WooCommerce 可以直接在服务端渲染 HTML，所以要直接访问上面的地址，或者在真实店铺域名后追加同一路径。

这不是加密逆向。真正需要逆向的接口会在请求中携带每次变化的 `sign` 或动态 `token`，并由页面脚本计算。本接口没有这些字段。

## 响应格式

练习店最初验证时有 10 个商品；后续新增商品后变成 11 个、6 页。商品数量会变化，程序必须读取响应头，不能把页数写死。使用 `per_page=2` 时，当时的结果是：

| 项目 | 实际结果 |
| --- | --- |
| 响应头 `X-WP-Total` | `10` |
| 响应头 `X-WP-TotalPages` | `5` |
| 第 1 到第 5 页 | 每页 2 条商品 |
| 第 6 页 | `200`，响应体是空数组 `[]` |
| 商品身份 | JSON 里的数字 `id` |
| 内容类型 | `application/json` |

分页结束条件是 `X-WP-TotalPages`。虽然第 6 页会返回空数组，程序也不能靠“再请求一页看看是否为空”决定停止，因为总页数已经明确放在响应头里。

后续入库时，商品唯一键使用：

```text
platform + shop + product_id
```

单独使用商品 `id` 不够，因为不同店铺可能出现相同的数字 ID。

## 价格不能直接读取

接口里的价格是最小货币单位的字符串，不是直接的元：

```json
{
  "prices": {
    "price": "1600",
    "currency_code": "CNY",
    "currency_minor_unit": 2
  }
}
```

还原公式是：

```text
金额 = int(prices.price) / 10 ** currency_minor_unit
```

因此 `"1600"` 和 `currency_minor_unit = 2` 表示 `16.00 CNY`。导入 CSV 中的 `16.00` 已通过接口验证会变成 `"1600"`。

有促销价时，`prices.price` 是当前生效价格，`prices.regular_price` 是原价。适配器要保留这两个值，不能只保存一个数字。

## 当前进度

`../first.py` 已经完成单进程采集。它读取 `X-WP-TotalPages` 翻页，并用 `currency_minor_unit` 还原价格。它只是采集函数，还不是分布式 Worker：没有从队列领取任务，也没有租约和 ACK。

真实站点已经做过一次契约对照。只请求了 WooCommerce 官方商店的 1 条商品，没有翻页，也没有保存商品内容。它的响应头、商品字段和价格结构与本地练习店一致，币种是 `USD`。这证明币种和小数位必须从接口读取。真实响应不入库、不提交到 GitHub。

## 本地练习店

`compose.yaml` 启动两个容器：

- `wordpress:6.7-php8.2-apache`：店铺和公开接口。容器首次启动后已在本地升级到 WordPress 7.1.4。
- `mariadb:11.4`：WordPress 自己的数据库。它不是采集结果数据库。

只在本机 `127.0.0.1` 发布端口，默认端口是 `8088`。

```bash
docker compose up -d
docker compose ps
```

停止容器但保留数据：

```bash
docker compose stop
```

`.env` 保存数据库密码和 WordPress 后台密码，已经被 Git 忽略。不要把真实密码写进 README、代码或提交记录。

首次安装 WordPress 后还需要启用 WooCommerce，并把固定链接设为 `/%postname%/`。否则 `/wp-json/...` 会返回 Apache 的 HTML 404。

`sample-products.csv` 是已经导入的 7 个示例商品。店铺中原有 3 个手工商品，总数因此是 10。

## 合规边界

- 日常开发和演示只请求本地练习店。
- 真实店铺只允许保存一页脱敏响应，用来对照字段；不连续翻页、不入库、不二次发布。
- 只采集公开商品字段。不登录，不访问订单、客户或后台管理接口。
- 不调用需要管理员密钥的 `/wp-json/wc/v3`。
- 收到 `401`、`403`、验证码或登录页时停止，不改用浏览器绕过。
- 浏览器降级以后只用于同一公开页面的 HTML 解析，并且必须单独限制次数。

## 采集结果数据库

当前采集结果已经改到仓库统一使用的 `crawler_platform`。本目录里的 `schema.sql` 和 `practice_shop` 只保留早期单进程验证记录，不再被 Flask 或 Worker 使用。

`products` 保存商品。唯一键是 `platform + shop + external_id`，重复运行时更新同一行，不新增第二行。

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `platform` | 固定值 `woocommerce` | 区分后续平台 |
| `shop` | 固定值 `local` | 区分不同店铺 |
| `external_id` | JSON 的 `id` | 原站商品身份 |
| `name` | `name` | 商品名称 |
| `currency_code` | `prices.currency_code` | 三位币种代码 |
| `minor_unit` | `prices.currency_minor_unit` | 小数位数 |
| `price_minor` | `prices.price` | 当前价格，保存最小货币单位 |
| `regular_price_minor` | `prices.regular_price` | 原价；接口为空时存 `NULL` |
| `sale_price_minor` | `prices.sale_price` | 促销价；接口为空时存 `NULL` |
| `on_sale` | `on_sale` | 是否促销 |
| `in_stock` | `is_in_stock` | 是否有库存 |
| `fetched_at` | 程序写入时间 | 最近一次抓取时间 |

价格不保存 `16.00` 这种小数。`1600` 这样的整数配合 `minor_unit`，显示时再换算，避免浮点误差。本地接口在没有促销时仍会返回数字形式的 `sale_price`，数值等于当前价格，不会返回空字符串。因此是否促销必须看 `on_sale`，不能靠 `sale_price_minor IS NULL` 判断。字段仍允许 `NULL`，只表示接口没有给出这个价格。

`crawl_pages` 保存页面进度。`shop + page_no` 是唯一键，`status` 只使用 `pending`、`done`、`failed`。当前程序会在一页商品全部保存成功后写入 `done`；商品保存中途崩溃时，这一页不会被标成完成。跳过已完成页面的逻辑还没有实现。

## 与采集服务的关系

本目录只提供本地店铺和公开接口。任务创建、Redis 调度、失败重试和结果入库由仓库根目录的 `crawler/` 实现。

## 当前目录

```text
woo-practice/
├── README.md
├── compose.yaml
├── sample-products.csv
├── .env.example
└── .gitignore
```

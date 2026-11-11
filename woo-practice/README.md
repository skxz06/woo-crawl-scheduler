# WooCommerce 公开接口采集练习

这是一个求职作品集项目的起点。当前目标不是大量采集，而是把一个真实电商公开接口看懂，并用可复现的本地店铺验证它的分页和价格规则。

本目录现在只负责本地练习店。正式的 Flask 后台、Redis 调度和 Worker 在仓库根目录的 `crawler/`，仓库总说明在根目录 `README.md`。

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

## 已验证的响应契约

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

## 上传到 GitHub 的范围

上传设计、代码、建表语句和可复现的示例数据。不上传密码、数据库导出、容器数据或真实店铺响应。

必须忽略：

- `.env`：数据库密码和 WordPress 后台密码。
- `wp/`、`bin/`、`*.tar`：容器数据、下载工具和镜像包。
- MySQL 数据目录及数据库备份。

README 要说明接口契约、本地启动方式、数据表和合规边界，但不写任何真实密码、后台用户名或个人邮箱。

## 计划中的结构

1. 单进程采集：已完成。
2. 真实接口对照：保存一页脱敏响应，确认字段和本地契约一致。
3. MySQL：以 `platform + shop + product_id` 做幂等写入，并保存页码断点。
4. Redis：用 Stream 消费组分配页面任务，用租约和 ACK 处理 Worker 崩溃。
5. Flask：提供启动任务、查看状态和重放死信的控制接口。
6. 降级：公开 JSON 失效后才解析同一公开 HTML；拒绝访问时进入死信，不启动浏览器。

MySQL 要先于 Redis。队列只能保证任务被分发，不能代替数据库的唯一键；没有唯一键时，重复投递和 Worker 崩溃恢复都会插入重复商品。

Redis 使用 Stream `woo:pages` 和消费组 `workers`。消息只保存 `shop` 和 `page`。Worker 用 `XREADGROUP` 领取新任务，处理完商品并写入 `crawl_pages` 后才 `XACK`。崩溃后超过 60 秒仍未确认的消息，由 `XAUTOCLAIM` 接管。

`app.py` 是控制面，只提供两个接口：

- `POST /crawl/start`：把练习店的 6 页放进 Redis。
- `GET /crawl/status`：返回 Stream 长度和未确认消息数。

本目录的早期独立控制面已经删除。采集调度由根目录 `crawler/` 中的 Flask 和 Worker 完成。

## 当前目录

```text
woo-practice/
├── README.md
├── app.py             # Flask 控制面
├── task_queue.py      # Redis Stream 队列
├── compose.yaml
├── schema.sql
├── sample-products.csv
├── .env               # 本地密码，不上传
└── .gitignore
```

# WooCommerce 采集调度系统

这个项目用一个真实的 WooCommerce 公开接口，演示采集系统的任务调度，而不是追求采集数量。

系统只有一条主链路：用户在 Flask 后台创建订单，独立 Worker 从 Redis 领取订单，请求店铺公开接口，并把商品写入 MySQL。

## 架构

```text
浏览器
  │ 登录、创建订单、查看进度、导出 CSV
  ▼
crawler/app.py
  │ 校验权限和 WooCommerce 参数
  │ 先写订单，再投递订单 ID
  ├──────────────────────────────┐
  ▼                              ▼
MySQL crawler_platform          Redis crawl:orders
用户、订单、商品                  待处理订单 ID
                                      │
                                      ▼
                               crawler/worker.py
                               领取、抓取、确认
                                      │
                                      ▼
                         /wp-json/wc/store/v1/products
```

四个组件的职责固定：

| 组件 | 职责 | 不负责 |
| --- | --- | --- |
| Flask | 登录、权限、创建订单、展示状态、导出 | 不抓取商品，不启动浏览器 |
| MySQL | 保存用户、订单状态和商品结果 | 不作为任务队列 |
| Redis | 分发订单、保存未确认消息、心跳和死信 | 不保存商品正文 |
| Worker | 领取订单、请求接口、写入结果、确认消息 | 不提供用户界面 |

这样拆分是为了让后台重启不影响正在执行的采集。Worker 在另一个进程中运行，崩溃后未确认的消息仍留在 Redis，超时后可以被接管。

## 设计原理

### 先写数据库，再入队

创建订单时先插入 MySQL，再把订单 ID 放入 Redis。队列消息只保存 ID，不保存商品数据。Worker 必须回表读取店铺地址、页数和每页数量。

这样 Redis 丢失时，订单仍然在数据库里；消息重复投递时，也可以根据订单状态和商品唯一键避免重复数据。

### MySQL 保证唯一，Redis 保证分发

商品唯一键是 `order_id + external_id`。同一个订单重复执行时更新原商品，不新增第二行。

Redis Stream 消费组保证一条新消息每次只被一个 Worker 领取。验证时 `worker-a` 和 `worker-b` 分别处理了订单 20、21，没有抢同一条消息。

### 失败按原因分级

| 响应 | 分类 | 处理 |
| --- | --- | --- |
| `401`、`403`、验证码、登录页 | 明确拒绝 | 立即失败并进入死信，不启动浏览器 |
| `429`、超时、连接失败 | 可恢复失败 | 消息不确认，60 秒后接管，最多 3 次 |
| `404` 或 JSON 接口返回 HTML | 契约失效 | 用本机 Chrome 读取同一站点公开的 `/shop/` |

浏览器只处理“公开接口不存在”，不能把拒绝访问变成另一次抓取。浏览器降级没有稳定的商品 ID，临时使用页面序号，因此不能替代 JSON 主接口。

### 权限边界

普通用户只能查看、导出和重试自己的订单。管理员可以查看所有订单和用户列表，并按用户导出 CSV。用户密码使用哈希校验，查询页面不返回密码字段。

## 已验证结果

- 未登录访问 `/` 返回 302，跳转到 `/login`。
- 创建 WooCommerce 订单后，Worker 请求公开 Store API。订单 27 由 `worker-1` 完成，保存了 2 个商品。
- 两个 Worker 同时等待时分别处理订单 20、21，未确认消息最终为 0。
- 连续 3 次失败后进入 `crawl:dead-letters`；`403` 第一次就进入死信。
- JSON 契约失效时，本机 Chrome 读取公开商店页并保存了 3 个商品。
- 普通用户访问 `/user/list` 会跳回订单列表；管理员可以打开用户列表。
- 失败分类测试位于 `crawler/tests/test_failure_policy.py`，不访问真实网站。

## 本地部署

商店不需要打包上传。`woo-practice/compose.yaml` 会在本地启动官方 WordPress 和 MariaDB 镜像，商品与后台数据保存在 Docker 卷中。别人克隆仓库后执行同样的 Compose 命令，会得到一套新的空店铺，再导入 `sample-products.csv` 即可复现。

```bash
cp woo-practice/.env.example woo-practice/.env
docker compose -f woo-practice/compose.yaml up -d
```

首次打开 `http://127.0.0.1:8088/`，完成 WordPress 安装，启用 WooCommerce，并把固定链接设为“文章名”。然后在后台导入 `woo-practice/sample-products.csv`。

采集系统还需要本机 MySQL 和 Redis。复制根目录配置后修改密码：

```bash
cp .env.example .env
mysql -h 127.0.0.1 -P 3307 -u root -p < schema.sql
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python crawler/app.py
.venv/bin/python crawler/worker.py worker-1
```

打开 `http://127.0.0.1:5000/`。未登录会进入登录页。

不要提交 `.env`、Docker 卷、数据库备份或镜像包。这些文件要么含有密码，要么体积大且只能在你的机器上使用。

## GitHub 仓库结构

```text
.
├── README.md
├── requirements.txt
├── schema.sql
├── .env.example
├── .gitignore
├── crawler/
│   ├── app.py
│   ├── worker.py
│   ├── utils/
│   ├── tests/
│   └── webapp/
└── woo-practice/
    ├── compose.yaml
    ├── .env.example
    ├── sample-products.csv
    └── README.md
```

不上传 `.env`、`.venv/`、`.idea/`、`__pycache__/`、`woo-practice/bin/` 和任何 `.tar` 镜像包。

## 目录

```text
.
├── README.md                 架构和运行说明
├── requirements.txt          Python 依赖
├── schema.sql                订单扩展字段和商品表
├── .env.example              配置模板，不含真实密码
├── crawler/
│   ├── app.py                Flask 入口
│   ├── worker.py             独立采集进程
│   ├── utils/                配置、MySQL、Redis
│   ├── tests/                失败分类测试
│   └── webapp/               蓝图、页面和权限
└── woo-practice/
    ├── compose.yaml          本地 WooCommerce 练习店
    ├── sample-products.csv   示例商品
    └── README.md             接口字段和分页说明
```

## 合规边界

只采集公开商品字段。不登录目标站，不访问订单、客户或后台管理接口，也不调用需要管理员密钥的 `/wp-json/wc/v3`。收到拒绝访问、验证码或登录页时停止，不改用浏览器绕过。

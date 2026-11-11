USE crawler_platform;

ALTER TABLE `order`
    ADD COLUMN attempts INT NOT NULL DEFAULT 0 COMMENT '已失败次数',
    ADD COLUMN worker_name VARCHAR(64) NULL COMMENT '最近领取该订单的 Worker',
    ADD COLUMN platform VARCHAR(32) NOT NULL DEFAULT 'woocommerce' COMMENT '采集平台',
    ADD COLUMN per_page INT NOT NULL DEFAULT 2 COMMENT '每页商品数';

CREATE TABLE IF NOT EXISTS products (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id      INT             NOT NULL,
    external_id   VARCHAR(64)     NOT NULL,
    name          VARCHAR(255)    NOT NULL,
    currency_code CHAR(3)         NOT NULL,
    minor_unit    TINYINT UNSIGNED NOT NULL,
    price_minor   BIGINT          NOT NULL,
    regular_price_minor BIGINT   NULL,
    on_sale       TINYINT(1)      NOT NULL,
    in_stock      TINYINT(1)      NOT NULL,
    fetched_at    DATETIME        NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_order_product (order_id, external_id),
    CONSTRAINT fk_product_order FOREIGN KEY (order_id) REFERENCES `order` (id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

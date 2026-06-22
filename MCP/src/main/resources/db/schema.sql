-- =====================================================================
-- 数码智能客服系统 — 表结构 (MySQL 8.0+, InnoDB, utf8mb4)
-- MySQL 保留 5 个权威库：用户信息(customer) / 商品库存(product) / 订单(orders) / 售后记录(after_sale) / 人工服务(human_service)。
--   · 商品「详细信息」(名称/分类/品牌/描述/规格)与「售后技术方案知识库」存于 Qdrant，
--     由 /admin/reindex 从 classpath 种子 JSON(seed/products.json, seed/knowledge.json) 灌入。
--   · 检索全部由 Qdrant 语义完成，MySQL 不再承担任何全文检索，故无 FULLTEXT 索引。
--   CREATE DATABASE digital_cs DEFAULT CHARSET utf8mb4; USE digital_cs;
-- =====================================================================

SET NAMES utf8mb4;

-- ------------------------- 1. 用户信息库 -------------------------
CREATE TABLE IF NOT EXISTS customer (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  customer_no  VARCHAR(32)  NOT NULL COMMENT '客户编号',
  nickname     VARCHAR(64)  DEFAULT NULL,
  phone        VARCHAR(20)  DEFAULT NULL,
  password     VARCHAR(128) NOT NULL DEFAULT '123456' COMMENT '登录密码(测试环境明文)',
  member_level TINYINT      NOT NULL DEFAULT 0 COMMENT '0普通 1银 2金 3铂金',
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_customer_no (customer_no),
  KEY idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户信息库';

-- ------------------------- 2. 商品库存库(纯库存；价格/发布时间/详情均在 Qdrant) -------------------------
CREATE TABLE IF NOT EXISTS product (
  id           BIGINT        NOT NULL AUTO_INCREMENT,
  product_no   VARCHAR(32)   NOT NULL COMMENT '商品编号(与 Qdrant 详情按此关联)',
  name         VARCHAR(128)  NOT NULL COMMENT '商品名称(展示/兜底用，权威在 Qdrant)',
  stock        INT           NOT NULL DEFAULT 0 COMMENT '可用库存',
  status       TINYINT       NOT NULL DEFAULT 1 COMMENT '0下架 1在售',
  created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  deleted      TINYINT       NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_product_no (product_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品库存库(纯库存，价格在 Qdrant)';

-- ------------------------- 3. 订单库(含明细/物流, JSON) -------------------------
CREATE TABLE IF NOT EXISTS orders (
  id             BIGINT        NOT NULL AUTO_INCREMENT,
  order_no       VARCHAR(32)   NOT NULL COMMENT '订单号',
  customer_id    BIGINT        NOT NULL,
  total_amount   DECIMAL(12,2) NOT NULL DEFAULT 0,
  pay_amount     DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '实付',
  order_status   TINYINT       NOT NULL DEFAULT 0 COMMENT '0待付款 1待发货 2待收货 3已完成 4已取消',
  pay_status     TINYINT       NOT NULL DEFAULT 0 COMMENT '0未付 1已付 2已退款',
  receiver_name  VARCHAR(64)   DEFAULT NULL,
  receiver_phone VARCHAR(20)   DEFAULT NULL,
  receiver_address VARCHAR(255) DEFAULT NULL,
  items          JSON          DEFAULT NULL COMMENT '订单明细 [{productNo,productName,spec,price,quantity}]',
  logistics      JSON          DEFAULT NULL COMMENT '物流 {company,trackingNo,status,traces:[{time,location,description}]}',
  created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_order_no (order_no),
  KEY idx_customer (customer_id),
  KEY idx_status (order_status),
  CONSTRAINT chk_order_single_item CHECK (items IS NULL OR JSON_LENGTH(items) = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单库';

-- ------------------------- 4. 售后记录库 -------------------------
CREATE TABLE IF NOT EXISTS after_sale (
  id             BIGINT        NOT NULL AUTO_INCREMENT,
  after_sale_no  VARCHAR(32)   NOT NULL COMMENT '售后单号',
  order_no       VARCHAR(32)   NOT NULL COMMENT '关联订单号',
  customer_id    BIGINT        NOT NULL,
  type           TINYINT       NOT NULL DEFAULT 1 COMMENT '1退货退款 2换货 3仅退款 4维修',
  reason         VARCHAR(512)  DEFAULT NULL COMMENT '售后原因',
  status         TINYINT       NOT NULL DEFAULT 0 COMMENT '0待审 1已通过 2已拒绝 3处理中 4已完成',
  remark         VARCHAR(512)  DEFAULT NULL COMMENT '处理备注',
  created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_after_sale_no (after_sale_no),
  KEY idx_order (order_no),
  KEY idx_customer (customer_id),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='售后记录库';

-- ------------------------- 5. 人工服务记录库 -------------------------
CREATE TABLE IF NOT EXISTS human_service (
  id                 BIGINT        NOT NULL AUTO_INCREMENT,
  service_no         VARCHAR(32)   NOT NULL COMMENT '人工服务单号',
  customer_id        BIGINT        NOT NULL,
  order_no           VARCHAR(32)   DEFAULT NULL COMMENT '关联订单号，可为空',
  after_sale_no      VARCHAR(32)   DEFAULT NULL COMMENT '关联售后单号，可为空',
  reason             VARCHAR(512)  NOT NULL COMMENT '转人工原因',
  status             TINYINT       NOT NULL DEFAULT 0 COMMENT '0待处理 1处理中 2已完成 3已关闭',
  remark             VARCHAR(512)  DEFAULT NULL COMMENT '处理备注',
  created_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_service_no (service_no),
  KEY idx_customer (customer_id),
  KEY idx_order (order_no),
  KEY idx_after_sale (after_sale_no),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人工服务记录库';

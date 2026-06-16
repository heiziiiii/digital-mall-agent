-- MySQL 种子数据(权威库)：6 客户 / 8 商品库存 / 8 订单(含物流) / 6 售后单 / 人工服务单。
-- 同时作为 docker 首次初始化与 POST /admin/reset 重置的单一数据源：
--   先 TRUNCATE 清空 5 张表(重置归零自增)，再重新灌入；表结构由 db/schema.sql 负责。
-- 商品详情与售后知识库不在 MySQL：由 seed/products.json、seed/knowledge.json 灌入 Qdrant(见 /admin/reindex、/admin/reset)。
-- 必须显式声明连接字符集：docker-entrypoint 对每个 .sql 文件单独建连，默认 latin1 会导致中文双重编码(乱码)。
SET NAMES utf8mb4;

TRUNCATE TABLE customer;
TRUNCATE TABLE product;
TRUNCATE TABLE orders;
TRUNCATE TABLE after_sale;
TRUNCATE TABLE human_service;

INSERT INTO customer (id, customer_no, nickname, phone, password, member_level)
VALUES
 (1, 'C100001', '张三', '13800001111', '123456', 2),
 (2, 'C100002', '李女士', '13900002222', '123456', 1),
 (3, 'C100003', '王先生', '13700003333', '123456', 3),
 (4, 'C100004', '赵敏', '13600004444', '123456', 0),
 (5, 'C100005', '陈工', '13500005555', '123456', 2),
 (6, 'C100006', '周同学', '13400006666', '123456', 1);

-- 商品库存库：纯库存；名称仅作展示兜底，价格/发布时间/详情(描述/规格)均在 Qdrant。product_no 与 seed/products.json 对应。
INSERT INTO product (id, product_no, name, stock, status)
VALUES
 (1, 'P10001', '极客Pro X1 旗舰手机', 120, 1),
 (2, 'P10002', '星云 Air 14 轻薄本', 35, 1),
 (3, 'P10003', '苹果 iPhone 15 Pro', 80, 1),
 (4, 'P10004', '三星 Galaxy S24 Ultra', 50, 1),
 (5, 'P10005', '华为 Mate 60 Pro', 60, 1),
 (6, 'P10006', '小米 14 Pro', 100, 1),
 (7, 'P10007', 'OPPO Find X7 Ultra', 40, 1),
 (8, 'P10008', 'vivo X100 Pro', 45, 1);

INSERT INTO orders (id, order_no, customer_id, total_amount, pay_amount, order_status, pay_status,
                    receiver_name, receiver_phone, receiver_address, items, logistics)
VALUES
 (1, 'O202606010001', 1, 3999.00, 3999.00, 2, 1, '张三', '13800001111', '上海市浦东新区xx路1号',
  '[{"productNo":"P10001","productName":"极客Pro X1 旗舰手机","spec":"曜石黑 256G","price":3999.00,"quantity":1}]',
  '{"company":"顺丰速运","trackingNo":"SF1234567890","status":2,"traces":[{"time":"2026-06-01 10:00","location":"上海揽收点","description":"顺丰速运已揽收"},{"time":"2026-06-01 14:00","location":"上海转运中心","description":"快件已到达【上海转运中心】"}]}'),
 (2, 'O202606020001', 2, 5299.00, 5299.00, 1, 1, '李女士', '13900002222', '北京市朝阳区望京SOHO T1',
  '[{"productNo":"P10002","productName":"星云 Air 14 轻薄本","spec":"银色 16G+512G","price":5299.00,"quantity":1}]',
  '{"company":"京东物流","trackingNo":"JD202606020001","status":1,"traces":[{"time":"2026-06-02 09:20","location":"北京仓","description":"订单已出库，等待揽收"}]}'),
 (3, 'O202606030001', 3, 18698.00, 18498.00, 3, 1, '王先生', '13700003333', '深圳市南山区科技园科苑路88号',
  '[{"productNo":"P10003","productName":"苹果 iPhone 15 Pro","spec":"原色钛金属 256G","price":8999.00,"quantity":1},{"productNo":"P10004","productName":"三星 Galaxy S24 Ultra","spec":"钛灰 512G","price":9699.00,"quantity":1}]',
  '{"company":"顺丰速运","trackingNo":"SF202606030001","status":3,"traces":[{"time":"2026-06-03 08:10","location":"深圳仓","description":"快件已发出"},{"time":"2026-06-03 18:40","location":"深圳南山营业点","description":"快件派送中"},{"time":"2026-06-03 20:10","location":"深圳市南山区","description":"已签收，签收人：本人"}]}'),
 (4, 'O202606040001', 4, 6999.00, 0.00, 0, 0, '赵敏', '13600004444', '杭州市西湖区文三路99号',
  '[{"productNo":"P10005","productName":"华为 Mate 60 Pro","spec":"雅川青 512G","price":6999.00,"quantity":1}]',
  NULL),
 (5, 'O202606040002', 5, 11298.00, 11298.00, 2, 1, '陈工', '13500005555', '广州市天河区体育西路66号',
  '[{"productNo":"P10006","productName":"小米 14 Pro","spec":"黑色 256G","price":5299.00,"quantity":1},{"productNo":"P10007","productName":"OPPO Find X7 Ultra","spec":"海阔天空 256G","price":5999.00,"quantity":1}]',
  '{"company":"中通快递","trackingNo":"ZTO202606040002","status":2,"traces":[{"time":"2026-06-04 11:30","location":"广州仓","description":"快件已揽收"},{"time":"2026-06-04 16:10","location":"广州转运中心","description":"快件运输中"}]}'),
 (6, 'O202606050001', 6, 4999.00, 4999.00, 4, 2, '周同学', '13400006666', '南京市鼓楼区汉口路22号',
  '[{"productNo":"P10008","productName":"vivo X100 Pro","spec":"星迹蓝 256G","price":4999.00,"quantity":1}]',
  '{"company":"圆通速递","trackingNo":"YTO202606050001","status":0,"traces":[]}'),
 (7, 'O202606050002', 1, 9699.00, 9699.00, 1, 1, '张三', '13800001111', '上海市浦东新区xx路1号',
  '[{"productNo":"P10004","productName":"三星 Galaxy S24 Ultra","spec":"钛黑 512G","price":9699.00,"quantity":1}]',
  '{"company":"顺丰速运","trackingNo":"SF202606050002","status":1,"traces":[{"time":"2026-06-05 13:00","location":"上海仓","description":"商家已通知快递取件"}]}'),
 (8, 'O202606060001', 3, 5299.00, 5299.00, 3, 1, '王先生', '13700003333', '深圳市南山区科技园科苑路88号',
  '[{"productNo":"P10006","productName":"小米 14 Pro","spec":"白色 512G","price":5299.00,"quantity":1}]',
  '{"company":"京东物流","trackingNo":"JD202606060001","status":3,"traces":[{"time":"2026-06-06 09:00","location":"深圳仓","description":"订单已出库"},{"time":"2026-06-06 12:20","location":"深圳南山站","description":"配送员正在派送"},{"time":"2026-06-06 15:05","location":"深圳市南山区","description":"已签收"}]}');

INSERT INTO after_sale (id, after_sale_no, order_no, customer_id, type, reason, status, remark)
VALUES
 (1, 'AS202606010001', 'O202606010001', 1, 1, '商品充电异常发热，申请退货退款', 0, NULL),
 (2, 'AS202606030001', 'O202606030001', 3, 2, '三星手机外包装破损，申请换货', 1, '已审核通过，等待用户寄回'),
 (3, 'AS202606040001', 'O202606040002', 5, 4, '小米手机摄像头偶发无法对焦，申请维修', 3, '维修中心已收件，预计2个工作日完成检测'),
 (4, 'AS202606050001', 'O202606050001', 6, 3, '订单取消后申请仅退款', 4, '退款已原路退回'),
 (5, 'AS202606060001', 'O202606060001', 3, 1, '不喜欢颜色，申请退货退款', 2, '商品已激活且影响二次销售，申请被拒绝'),
 (6, 'AS202606050002', 'O202606050002', 1, 2, '想更换钛灰颜色', 0, NULL);

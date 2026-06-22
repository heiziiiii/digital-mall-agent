"""
从 phone.csv 生成两个种子文件：
  - ../src/main/resources/seed/products.json  (Qdrant 向量库种子)
  - ../src/main/resources/seed/mysql.sql      (MySQL product 部分 + 保留其余 customer/orders/after_sale)

策略：
  - 选 15 个主流品牌，每品牌最多 8 款（仅有价格的型号）
  - 约 100–120 条商品，product_no = P10001 起
  - stock 随机 10–300
  - 解析 CPU / RAM+Storage / 电池 / 系统 / 摄像头 主像素 等字段
"""

import csv
import json
import re
import random
import os

random.seed(42)

CSV_PATH = os.path.join(os.path.dirname(__file__), "phone.csv")
OUT_PRODUCTS = os.path.join(os.path.dirname(__file__),
                            "../src/main/resources/seed/products.json")
OUT_MYSQL    = os.path.join(os.path.dirname(__file__),
                            "../src/main/resources/seed/mysql.sql")

TARGET_BRANDS = [
    "苹果", "三星", "华为", "小米", "vivo", "OPPO",
    "荣耀", "红米", "真我", "一加", "索尼",
    "联想", "努比亚", "HTC", "Moto",
]
MAX_PER_BRAND = 8

def clean_cpu(raw: str) -> str:
    """从 'CPU型号高通 骁龙8 Gen1' → '高通 骁龙8 Gen1'"""
    s = raw.strip()
    s = re.sub(r"^CPU型号\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    return s[:80] if s else "未知"

def clean_memory(raw: str) -> str:
    """从 '12GB 256GB ' → '12GB+256GB'"""
    s = raw.strip()
    s = re.sub(r"^(后置摄像头\d+|前置摄像头\d+|ROM容量)\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    m = re.findall(r"\d+GB|\d+MB|\d+TB", s)
    if m:
        return "+".join(m[:2])
    return s[:40] if s else "未知"

def clean_battery(raw: str) -> str:
    """提取 '5000mAh'，无法解析时返回空串"""
    m = re.search(r"(\d+)\s*mAh", raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}mAh"
    s = raw.strip()
    if not s or s in ("空", "无", "N/A"):
        return ""
    return s[:20]

def clean_os(raw: str) -> str:
    """从 '操作系统Android 13' → 'Android 13'"""
    s = raw.strip()
    s = re.sub(r"^操作系统\s*", "", s)
    return s[:40] if s else "未知"

def extract_main_camera(raw: str) -> str:
    """从长摄像头描述提取主摄像素，如 '6400万像素'"""
    m = re.search(r"后置主摄[^：]*：\s*(\d+)万像素", raw)
    if m:
        return f"{m.group(1)}万像素"
    m = re.search(r"(\d+)万像素", raw)
    if m:
        return f"{m.group(1)}万像素"
    return "未知"

def extract_front_camera(raw: str) -> str:
    m = re.search(r"前置[^：]*：\s*(\d+)万像素", raw)
    if m:
        return f"{m.group(1)}万像素"
    return "未知"

def clean_rating(raw: str) -> float:
    """从 '9.6星' → 9.6，无评价 → None"""
    s = raw.strip()
    if "无评价" in s or not s:
        return None
    m = re.search(r"([\d.]+)星", s)
    if m:
        return float(m.group(1))
    return None

def clean_colors(raw: str) -> list:
    s = raw.strip().strip('"')
    s = re.sub(r"^机身颜色\s*", "", s)
    parts = re.split(r"[，,、/\s]{1,2}", s)
    result = []
    for p in parts:
        p = p.strip()
        if p and 1 < len(p) <= 10:
            result.append(p)
    return result[:4]

def price_tags(price: float) -> list:
    if price >= 6000:
        return ["旗舰机型", "高端"]
    elif price >= 3000:
        return ["中高端", "性价比高"]
    elif price >= 1500:
        return ["中端", "性价比高"]
    else:
        return ["入门", "性价比高"]

def battery_tag(battery_str: str) -> list:
    m = re.search(r"(\d+)mAh", battery_str, re.I)
    if m and int(m.group(1)) >= 5000:
        return ["大电池", "续航久"]
    return ["续航标准"]

def ram_tag(memory_str: str) -> list:
    m = re.search(r"(\d+)GB", memory_str)
    if m and int(m.group(1)) >= 12:
        return ["大内存"]
    return []

def make_description(name, brand, cpu, memory, battery, main_cam, os_str) -> str:
    parts = [f"{name}搭载{cpu}处理器"]
    mem = memory.replace("+", " RAM + ")
    if mem and mem != "未知":
        parts.append(f"配备{mem}存储组合")
    if battery:
        parts.append(f"内置{battery}电池")
    if main_cam and main_cam != "未知":
        parts.append(f"主摄达{main_cam}")
    if os_str and os_str != "未知":
        parts.append(f"搭载{os_str}系统")
    return "，".join(parts) + "。"

def make_subtitle(cpu, memory, battery) -> str:
    parts = []
    cpu_short = re.sub(r"^(高通|联发科|苹果|英特尔|三星|海思)\s*", "", cpu)[:20]
    if cpu_short:
        parts.append(cpu_short)
    if memory and memory != "未知":
        parts.append(memory)
    if battery:
        parts.append(battery)
    return " / ".join(parts) if parts else ""

def read_csv():
    rows = []
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if len(row) < 10:
                continue
            brand = row[0].strip()
            model = row[1].strip()
            colors_raw = row[2]
            price_raw = row[3].strip()
            cpu_raw = row[4]
            memory_raw = row[5]
            battery_raw = row[6]
            os_raw = row[7]
            camera_raw = row[8]
            rating_raw = row[9]

            if not price_raw or "暂无" in price_raw or not price_raw.replace(".", "").isdigit():
                try:
                    price = float(re.search(r"[\d.]+", price_raw).group())
                except:
                    continue

            try:
                price = float(price_raw)
            except:
                continue

            os_str = clean_os(os_raw)
            if brand == "苹果" and "iOS" not in os_str:
                os_str = "iOS"

            rows.append({
                "brand": brand,
                "model": model,
                "colors": clean_colors(colors_raw),
                "price": price,
                "cpu": clean_cpu(cpu_raw),
                "memory": clean_memory(memory_raw),
                "battery": clean_battery(battery_raw),
                "os": os_str,
                "main_cam": extract_main_camera(camera_raw),
                "front_cam": extract_front_camera(camera_raw),
                "rating": clean_rating(rating_raw),
            })
    return rows

def sample_products(rows):
    by_brand = {}
    for r in rows:
        by_brand.setdefault(r["brand"], []).append(r)

    selected = []
    for brand in TARGET_BRANDS:
        items = by_brand.get(brand, [])
        items_sorted = sorted(items, key=lambda x: -x["price"])
        selected.extend(items_sorted[:MAX_PER_BRAND])
    return selected

def make_products_json(selected):
    products = []
    for i, r in enumerate(selected, start=1):
        product_no = f"P{10000 + i}"
        market_price = round(r["price"] * random.uniform(1.05, 1.12), 2)
        tags = (price_tags(r["price"])
                + battery_tag(r["battery"])
                + ram_tag(r["memory"]))
        tags = list(dict.fromkeys(tags))[:5]

        subtitle = make_subtitle(r["cpu"], r["memory"], r["battery"])
        description = make_description(
            r["model"], r["brand"],
            r["cpu"], r["memory"], r["battery"],
            r["main_cam"], r["os"]
        )

        specs = []
        if r["cpu"] and r["cpu"] != "未知":
            specs.append({"name": "处理器", "value": r["cpu"]})
        if r["memory"] and r["memory"] != "未知":
            specs.append({"name": "存储", "value": r["memory"]})
        if r["battery"]:
            specs.append({"name": "电池", "value": r["battery"]})
        if r["os"] and r["os"] != "未知":
            specs.append({"name": "操作系统", "value": r["os"]})
        if r["main_cam"] and r["main_cam"] != "未知":
            specs.append({"name": "主摄像素", "value": r["main_cam"]})
        if r["front_cam"] and r["front_cam"] != "未知":
            specs.append({"name": "前摄像素", "value": r["front_cam"]})
        if r["colors"]:
            specs.append({"name": "颜色", "value": "、".join(r["colors"])})
        if r["rating"]:
            specs.append({"name": "好评率", "value": f"{r['rating']}星"})

        products.append({
            "productNo": product_no,
            "name": r["model"],
            "subtitle": subtitle,
            "category": "手机",
            "brand": r["brand"],
            "tags": tags,
            "price": r["price"],
            "marketPrice": market_price,
            "publishedAt": "2024-01-01",
            "description": description,
            "specs": specs,
        })
    return products

MYSQL_HEADER = """\
-- MySQL 种子数据 (权威库): 商品库存由 phone.csv 自动生成, 库存随机。
-- 其余 customer / orders / after_sale / human_service 保持不变。
-- 同时作为 docker 首次初始化与 POST /admin/reset 重置的单一数据源。
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

"""

def make_mysql_sql(selected):
    lines = [MYSQL_HEADER]
    lines.append("-- 商品库存库：stock 随机生成，product_no 与 seed/products.json 对应。")
    lines.append("INSERT INTO product (id, product_no, name, stock, status) VALUES")
    rows_sql = []
    for i, r in enumerate(selected, start=1):
        product_no = f"P{10000 + i}"
        name = r["model"].replace("'", "\\'")
        stock = random.randint(10, 300)
        rows_sql.append(f" ({i}, '{product_no}', '{name}', {stock}, 1)")
    lines.append(",\n".join(rows_sql) + ";")

    p = [f"P{10001 + i}" for i in range(8)]
    names = [selected[i]["model"].replace("'", "\\'") for i in range(8)]
    prices = [selected[i]["price"] for i in range(8)]

    lines.append("""
INSERT INTO orders (id, order_no, customer_id, total_amount, pay_amount, order_status, pay_status,
                    receiver_name, receiver_phone, receiver_address, items, logistics)
VALUES""")

    def item_json(pno, pname, price, qty=1):
        return json.dumps([{"productNo": pno, "productName": pname, "price": price, "quantity": qty}],
                          ensure_ascii=False)

    def logistics_json(company, tracking, status, traces):
        return json.dumps({"company": company, "trackingNo": tracking, "status": status, "traces": traces},
                          ensure_ascii=False)

    orders = [
        (1, 'O202606010001', 1, prices[0], prices[0], 2, 1, '张三', '13800001111', '上海市浦东新区xx路1号',
         item_json(p[0], names[0], prices[0]),
         logistics_json('顺丰速运', 'SF1234567890', 2,
                        [{"time": "2026-06-01 10:00", "location": "上海揽收点", "description": "顺丰速运已揽收"},
                         {"time": "2026-06-01 14:00", "location": "上海转运中心", "description": "快件已到达【上海转运中心】"}])),
        (2, 'O202606020001', 2, prices[1], prices[1], 1, 1, '李女士', '13900002222', '北京市朝阳区望京SOHO T1',
         item_json(p[1], names[1], prices[1]),
         logistics_json('京东物流', 'JD202606020001', 1,
                        [{"time": "2026-06-02 09:20", "location": "北京仓", "description": "订单已出库，等待揽收"}])),
        (3, 'O202606030001', 3, prices[2] + prices[3], prices[2] + prices[3], 3, 1, '王先生', '13700003333', '深圳市南山区科技园科苑路88号',
         json.dumps([{"productNo": p[2], "productName": names[2], "price": prices[2], "quantity": 1},
                     {"productNo": p[3], "productName": names[3], "price": prices[3], "quantity": 1}], ensure_ascii=False),
         logistics_json('顺丰速运', 'SF202606030001', 3,
                        [{"time": "2026-06-03 08:10", "location": "深圳仓", "description": "快件已发出"},
                         {"time": "2026-06-03 20:10", "location": "深圳市南山区", "description": "已签收，签收人：本人"}])),
        (4, 'O202606040001', 4, prices[4], 0.0, 0, 0, '赵敏', '13600004444', '杭州市西湖区文三路99号',
         item_json(p[4], names[4], prices[4]), 'NULL'),
        (5, 'O202606040002', 5, prices[5] + prices[6], prices[5] + prices[6], 2, 1, '陈工', '13500005555', '广州市天河区体育西路66号',
         json.dumps([{"productNo": p[5], "productName": names[5], "price": prices[5], "quantity": 1},
                     {"productNo": p[6], "productName": names[6], "price": prices[6], "quantity": 1}], ensure_ascii=False),
         logistics_json('中通快递', 'ZTO202606040002', 2,
                        [{"time": "2026-06-04 11:30", "location": "广州仓", "description": "快件已揽收"},
                         {"time": "2026-06-04 16:10", "location": "广州转运中心", "description": "快件运输中"}])),
        (6, 'O202606050001', 6, prices[7], prices[7], 4, 2, '周同学', '13400006666', '南京市鼓楼区汉口路22号',
         item_json(p[7], names[7], prices[7]),
         logistics_json('圆通速递', 'YTO202606050001', 0, [])),
        (7, 'O202606050002', 1, prices[3], prices[3], 1, 1, '张三', '13800001111', '上海市浦东新区xx路1号',
         item_json(p[3], names[3], prices[3]),
         logistics_json('顺丰速运', 'SF202606050002', 1,
                        [{"time": "2026-06-05 13:00", "location": "上海仓", "description": "商家已通知快递取件"}])),
        (8, 'O202606060001', 3, prices[5], prices[5], 3, 1, '王先生', '13700003333', '深圳市南山区科技园科苑路88号',
         item_json(p[5], names[5], prices[5]),
         logistics_json('京东物流', 'JD202606060001', 3,
                        [{"time": "2026-06-06 09:00", "location": "深圳仓", "description": "订单已出库"},
                         {"time": "2026-06-06 15:05", "location": "深圳市南山区", "description": "已签收"}])),
    ]

    order_rows = []
    for o in orders:
        (oid, order_no, cid, total, pay, ostatus, pstatus,
         rname, rphone, raddr, items_j, logistics_j) = o
        name_esc = rname.replace("'", "\\'")
        addr_esc = raddr.replace("'", "\\'")
        items_esc = items_j.replace("'", "\\'") if items_j != 'NULL' else None
        logi_esc = logistics_j.replace("'", "\\'") if logistics_j != 'NULL' else None
        items_sql = f"'{items_esc}'" if items_esc else 'NULL'
        logi_sql = f"'{logi_esc}'" if logi_esc else 'NULL'
        order_rows.append(
            f" ({oid}, '{order_no}', {cid}, {total:.2f}, {pay:.2f}, {ostatus}, {pstatus},"
            f" '{name_esc}', '{rphone}', '{addr_esc}', {items_sql}, {logi_sql})"
        )
    lines.append(",\n".join(order_rows) + ";")

    lines.append("""
INSERT INTO after_sale (id, after_sale_no, order_no, customer_id, type, reason, status, remark)
VALUES
 (1, 'AS202606010001', 'O202606010001', 1, 1, '商品充电异常发热，申请退货退款', 0, NULL),
 (2, 'AS202606030001', 'O202606030001', 3, 2, '手机外包装破损，申请换货', 1, '已审核通过，等待用户寄回'),
 (3, 'AS202606040001', 'O202606040002', 5, 4, '摄像头偶发无法对焦，申请维修', 3, '维修中心已收件，预计2个工作日完成检测'),
 (4, 'AS202606050001', 'O202606050001', 6, 3, '订单取消后申请仅退款', 4, '退款已原路退回'),
 (5, 'AS202606060001', 'O202606060001', 3, 1, '不喜欢颜色，申请退货退款', 2, '商品已激活且影响二次销售，申请被拒绝'),
 (6, 'AS202606050002', 'O202606050002', 1, 2, '想更换颜色', 0, NULL);
""")

    return "\n".join(lines)

if __name__ == "__main__":
    print("Reading CSV...")
    rows = read_csv()
    print(f"Total valid rows: {len(rows)}")

    selected = sample_products(rows)
    print(f"Selected products: {len(selected)}")

    from collections import Counter
    dist = Counter(r["brand"] for r in selected)
    for b, c in dist.most_common():
        print(f"  {b}: {c}")

    products = make_products_json(selected)
    mysql_sql = make_mysql_sql(selected)

    out_p = os.path.abspath(OUT_PRODUCTS)
    out_m = os.path.abspath(OUT_MYSQL)

    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(products)} products to:\n  {out_p}")

    with open(out_m, "w", encoding="utf-8") as f:
        f.write(mysql_sql)
    print(f"Wrote MySQL seed to:\n  {out_m}")

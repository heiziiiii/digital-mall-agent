# -*- coding: utf-8 -*-
"""MCP SSE 测试客户端：连接 digital-cs-mcp，逐个调用全部工具并打印结果。"""
import io
import json
import os
import sys
import threading
import time
import queue
import urllib.request

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免打印中文结果时 UnicodeEncodeError
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://localhost:8080"
io_in = queue.Queue()          # SSE 收到的 message 事件
endpoint_holder = {}           # 存放 server 下发的 message 端点

def sse_reader():
    """读取 /sse 流：解析 endpoint 事件与 message 事件。"""
    req = urllib.request.Request(BASE + "/sse", headers={"Accept": "text/event-stream"})
    resp = urllib.request.urlopen(req, timeout=30)
    event = None
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data = line[len("data:"):].strip()
            if event == "endpoint":
                endpoint_holder["url"] = data
            elif event == "message":
                io_in.put(data)
        elif line == "":
            event = None

def post(payload):
    url = BASE + endpoint_holder["url"]
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()

def wait_for(req_id, timeout=30):
    """等待匹配 id 的 JSON-RPC 响应。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            data = io_in.get(timeout=end - time.time())
        except queue.Empty:
            break
        msg = json.loads(data)
        if msg.get("id") == req_id:
            return msg
    raise TimeoutError(f"no response for id={req_id}")

def call_tool(req_id, name, args):
    post({"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    resp = wait_for(req_id)
    return resp

def main():
    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    # 等待 endpoint
    for _ in range(50):
        if "url" in endpoint_holder:
            break
        time.sleep(0.1)
    if "url" not in endpoint_holder:
        print("ERROR: 未收到 SSE endpoint"); sys.exit(1)
    print("SSE endpoint:", endpoint_holder["url"])

    # initialize
    post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05",
                     "capabilities": {},
                     "clientInfo": {"name": "test", "version": "1.0"}}})
    init = wait_for(1)
    print("\n== initialize ==")
    print(json.dumps(init.get("result", {}).get("serverInfo", {}), ensure_ascii=False))
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # tools/list
    post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = wait_for(2)
    names = [tdef["name"] for tdef in tools["result"]["tools"]]
    print("\n== tools/list ({}) ==".format(len(names)))
    print(names)

    # 逐个调用
    cases = [
        ("searchProducts",       {"query": "手机", "limit": 5}),
        ("searchProducts",       {"query": "轻薄本"}),
        ("searchProducts",       {"category": "手机", "brand": "极客Pro", "limit": 3}),
        ("getProductDetail",     {"productNo": "P10001"}),
        ("getProductDetail",     {"productNo": "NOPE"}),
        # 涉及个人数据的工具均需传入当前操作用户ID userId(自助模式：只能访问自己的数据)
        ("queryOrder",           {"userId": 1, "orderNo": "O202606010001"}),
        ("listCustomerOrders",   {"userId": 1}),
        ("trackLogistics",       {"userId": 1, "orderNo": "O202606010001"}),
        ("queryAfterSale",       {"userId": 1, "afterSaleNo": "AS202606010001"}),
        ("listOrderAfterSales",  {"userId": 1, "orderNo": "O202606010001"}),
        ("listCustomerAfterSales", {"userId": 1}),
        ("searchKnowledge",      {"query": "充电发热怎么办", "topK": 3}),
    ]
    if os.getenv("MCP_RUN_WRITE_TESTS") == "1":
        cases.append(("createAfterSale", {"userId": 1, "orderNo": "O202606010001", "type": 4,
                                          "reason": "屏幕有亮点申请维修"}))
        cases.append(("createHumanService", {"userId": 1, "orderNo": "O202606010001",
                                             "reason": "用户要求人工客服进一步处理"}))
    rid = 10
    for name, args in cases:
        rid += 1
        try:
            resp = call_tool(rid, name, args)
            res = resp.get("result", {})
            is_err = res.get("isError", False)
            content = res.get("content", [])
            text = content[0].get("text") if content else json.dumps(res, ensure_ascii=False)
            tag = "ERROR" if (is_err or "error" in resp) else "OK"
            if "error" in resp:
                text = json.dumps(resp["error"], ensure_ascii=False)
            print(f"\n== {name} {json.dumps(args, ensure_ascii=False)} -> {tag} ==")
            print((text or "")[:600])
        except Exception as e:
            print(f"\n== {name} -> EXCEPTION: {e} ==")

if __name__ == "__main__":
    main()

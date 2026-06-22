package com.digitalcs.mcp.web;

import com.digitalcs.mcp.service.AfterSaleService;
import com.digitalcs.mcp.service.OrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 客户自助 REST 接口：供前端「我的订单 / 我的售后」页面直接拉取结构化数据。
 *
 * <p>身份只信任网关注入的 {@code X-Customer-Id}（自助模式：只能看自己的数据），
 * 与 MCP 工具复用同一套 Service 鉴权逻辑；缺少身份一律按未授权处理。
 */
@RestController
@RequestMapping("/api/customer")
@RequiredArgsConstructor
public class CustomerSelfController {

    private final OrderService orderService;
    private final AfterSaleService afterSaleService;

    @GetMapping("/orders")
    public ApiResponse<Object> myOrders(@RequestHeader(value = "X-Customer-Id", required = false) Long userId) {
        return list(orderService.listMyOrders(userId), "orders");
    }

    @GetMapping("/orders/{orderNo}")
    public ApiResponse<Object> orderDetail(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String orderNo) {
        return detail(orderService.queryByOrderNo(orderNo, userId), "order");
    }

    @GetMapping("/aftersales")
    public ApiResponse<Object> myAfterSales(@RequestHeader(value = "X-Customer-Id", required = false) Long userId) {
        return list(afterSaleService.listMyAfterSales(userId), "afterSales");
    }

    @GetMapping("/aftersales/{afterSaleNo}")
    public ApiResponse<Object> afterSaleDetail(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String afterSaleNo) {
        return detail(afterSaleService.queryByNo(afterSaleNo, userId), "afterSale");
    }

    @PostMapping("/orders")
    public ApiResponse<Object> createOrder(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @RequestBody CreateOrderRequest req) {
        int quantity = req.quantity() == null ? 1 : req.quantity();
        return action(orderService.createOrder(
                userId, req.productNo(), quantity, req.spec(),
                req.receiverName(), req.receiverPhone(), req.receiverAddress()), "order");
    }

    @PostMapping("/orders/{orderNo}/cancel")
    public ApiResponse<Object> cancelOrder(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String orderNo) {
        return action(orderService.cancelOrder(orderNo, userId), "order");
    }

    @PostMapping("/aftersales/{afterSaleNo}/cancel")
    public ApiResponse<Object> cancelAfterSale(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String afterSaleNo) {
        return action(afterSaleService.cancel(afterSaleNo, userId), null);
    }

    private ApiResponse<Object> list(Map<String, Object> result, String dataKey) {
        if (Boolean.TRUE.equals(result.get("authorized"))) {
            return ApiResponse.ok(result.get(dataKey));
        }
        return ApiResponse.error(403, message(result, "无权访问"));
    }

    private ApiResponse<Object> detail(Map<String, Object> result, String dataKey) {
        if (Boolean.TRUE.equals(result.get("found"))) {
            return ApiResponse.ok(result.get(dataKey));
        }
        return ApiResponse.error(404, message(result, "未找到记录"));
    }

    /**
     * 操作类结果（撤销等）：ok=true 成功；否则按 authorized/found/状态依次映射为 403/404/409。
     * dataKey 为空表示无需回传业务数据。
     */
    private ApiResponse<Object> action(Map<String, Object> result, String dataKey) {
        if (Boolean.TRUE.equals(result.get("ok"))) {
            return ApiResponse.ok(dataKey == null ? null : result.get(dataKey));
        }
        if (Boolean.FALSE.equals(result.get("authorized"))) {
            return ApiResponse.error(403, message(result, "无权操作"));
        }
        if (Boolean.FALSE.equals(result.get("found"))) {
            return ApiResponse.error(404, message(result, "未找到记录"));
        }
        return ApiResponse.error(409, message(result, "当前状态不可撤销"));
    }

    private String message(Map<String, Object> result, String fallback) {
        Object message = result.get("message");
        return message == null ? fallback : String.valueOf(message);
    }

    public record CreateOrderRequest(
            String productNo,
            Integer quantity,
            String spec,
            String receiverName,
            String receiverPhone,
            String receiverAddress) {
    }
}

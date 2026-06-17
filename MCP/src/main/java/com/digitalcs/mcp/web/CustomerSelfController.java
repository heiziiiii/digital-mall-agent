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

    /** 当前用户的订单列表（按创建时间倒序）。 */
    @GetMapping("/orders")
    public ApiResponse<Object> myOrders(@RequestHeader(value = "X-Customer-Id", required = false) Long userId) {
        return list(orderService.listMyOrders(userId), "orders");
    }

    /** 当前用户某一订单的详情（含明细、物流、收货信息）。 */
    @GetMapping("/orders/{orderNo}")
    public ApiResponse<Object> orderDetail(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String orderNo) {
        return detail(orderService.queryByOrderNo(orderNo, userId), "order");
    }

    /** 当前用户的售后列表（按创建时间倒序）。 */
    @GetMapping("/aftersales")
    public ApiResponse<Object> myAfterSales(@RequestHeader(value = "X-Customer-Id", required = false) Long userId) {
        return list(afterSaleService.listMyAfterSales(userId), "afterSales");
    }

    /** 当前用户某一售后单的详情。 */
    @GetMapping("/aftersales/{afterSaleNo}")
    public ApiResponse<Object> afterSaleDetail(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String afterSaleNo) {
        return detail(afterSaleService.queryByNo(afterSaleNo, userId), "afterSale");
    }

    /** 下单：创建一笔「待付款」订单（数量缺省为 1），扣减库存后写入。 */
    @PostMapping("/orders")
    public ApiResponse<Object> createOrder(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @RequestBody CreateOrderRequest req) {
        int quantity = req.quantity() == null ? 1 : req.quantity();
        return action(orderService.createOrder(
                userId, req.productNo(), quantity, req.spec(),
                req.receiverName(), req.receiverPhone(), req.receiverAddress()), "order");
    }

    /** 撤销订单：仅「待付款」订单可撤销，撤销后置为已取消。 */
    @PostMapping("/orders/{orderNo}/cancel")
    public ApiResponse<Object> cancelOrder(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String orderNo) {
        return action(orderService.cancelOrder(orderNo, userId), "order");
    }

    /** 撤销售后：仅「待审核」售后单可撤销，撤销即删除该申请。 */
    @PostMapping("/aftersales/{afterSaleNo}/cancel")
    public ApiResponse<Object> cancelAfterSale(
            @RequestHeader(value = "X-Customer-Id", required = false) Long userId,
            @PathVariable String afterSaleNo) {
        return action(afterSaleService.cancel(afterSaleNo, userId), null);
    }

    /** 列表类结果：Service 已鉴权，authorized=true 时取出列表，否则按无权访问返回。 */
    private ApiResponse<Object> list(Map<String, Object> result, String dataKey) {
        if (Boolean.TRUE.equals(result.get("authorized"))) {
            return ApiResponse.ok(result.get(dataKey));
        }
        return ApiResponse.error(403, message(result, "无权访问"));
    }

    /** 详情类结果：found=true 取出数据；未找到或越权按 404 返回（不区分以免泄露归属）。 */
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

    /** 下单请求体：收货信息可选，缺省按空字符串处理。 */
    public record CreateOrderRequest(
            String productNo,
            Integer quantity,
            String spec,
            String receiverName,
            String receiverPhone,
            String receiverAddress) {
    }
}

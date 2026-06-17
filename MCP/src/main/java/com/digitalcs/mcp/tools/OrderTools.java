package com.digitalcs.mcp.tools;

import com.digitalcs.mcp.service.OrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.Map;

@Component
@RequiredArgsConstructor
public class OrderTools {

    private final OrderService orderService;

    @Tool(description = "查询指定订单的商品明细、订单状态、物流概况和关联售后。适合客户已提供订单号，或围绕某一笔订单询问买了什么、进展到哪、是否发货等问题；没有订单号时先用 listCustomerOrders 定位。")
    public Map<String, Object> queryOrder(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "订单号(order_no)") String orderNo) {
        return orderService.queryByOrderNo(orderNo, userId);
    }

    @Tool(description = "列出当前客户的订单记录，用来帮助客户从近期订单、某段时间、某个商品等线索中找到目标订单。客户确认具体订单后，再用 queryOrder 查详情或 trackLogistics 查物流。")
    public Map<String, Object> listCustomerOrders(
            @ToolParam(description = "当前会话客户ID") Long userId) {
        return orderService.listMyOrders(userId);
    }

    @Tool(description = "查询指定订单的发货状态和物流轨迹。适合客户关心快递到哪了、是否发货、什么时候能到等物流问题；如果还需要订单内容或售后概况，改用 queryOrder。")
    public Map<String, Object> trackLogistics(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "订单号(order_no)") String orderNo) {
        return orderService.trackLogistics(orderNo, userId);
    }

    @Tool(description = "为当前客户创建一笔待付款订单。仅在客户明确决定购买某个商品时使用；调用前必须确认商品编号、购买数量、收货人、手机号和收货地址。该写操作需要用户先核对确认，确认后才会真正扣减库存并生成订单。")
    public Map<String, Object> createOrder(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "商品编号(product_no)") String productNo,
            @ToolParam(description = "购买数量，必须大于0") Integer quantity,
            @ToolParam(description = "商品规格，例如颜色/内存；没有则传空字符串") String spec,
            @ToolParam(description = "收货人姓名") String receiverName,
            @ToolParam(description = "收货手机号") String receiverPhone,
            @ToolParam(description = "收货地址") String receiverAddress) {
        return orderService.createOrder(
                userId,
                productNo,
                quantity,
                spec,
                receiverName,
                receiverPhone,
                receiverAddress);
    }
}

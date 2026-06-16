package com.digitalcs.mcp.tools;

import com.digitalcs.mcp.service.AfterSaleService;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 售后域 MCP 工具：售后单的查询与创建。
 */
@Component
@RequiredArgsConstructor
public class AfterSaleTools {

    private final AfterSaleService afterSaleService;

    @Tool(description = "查询指定售后单的类型、原因和处理进度。适合客户已提供售后单号，或追问某次退款、换货、维修进展时使用；如果客户说不出售后单号，先通过订单或客户售后列表帮他定位。")
    public Map<String, Object> queryAfterSale(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "售后单号(after_sale_no)") String afterSaleNo) {
        return afterSaleService.queryByNo(afterSaleNo, userId);
    }

    @Tool(description = "查询某个订单关联的售后记录。适合客户围绕一笔订单询问退款、退换货、维修记录，或准备再次申请售后前先确认是否已有申请；要看单条售后进度时再使用 queryAfterSale。")
    public Map<String, Object> listOrderAfterSales(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "订单号(order_no)") String orderNo) {
        return afterSaleService.listByOrderNo(orderNo, userId);
    }

    @Tool(description = "列出当前客户的售后申请。适合客户笼统询问自己的售后、退款或申请记录时使用；客户选定某一条后，再用 queryAfterSale 查看详情。")
    public Map<String, Object> listCustomerAfterSales(
            @ToolParam(description = "当前会话客户ID") Long userId) {
        return afterSaleService.listMyAfterSales(userId);
    }

    @Tool(description = "为客户的订单提交售后申请，支持退货退款、换货、仅退款和维修。只在客户明确要办理售后时使用；调用前先确认订单号、售后类型和原因，调用后说明已提交处理，不要承诺审核结果或到账时间。")
    public Map<String, Object> createAfterSale(
            @ToolParam(description = "当前会话客户ID") Long userId,
            @ToolParam(description = "订单号(order_no)") String orderNo,
            @ToolParam(description = "售后类型: 1退货退款 2换货 3仅退款 4维修") Integer type,
            @ToolParam(description = "售后原因") String reason) {
        return afterSaleService.create(orderNo, userId, type, reason);
    }
}

package com.digitalcs.mcp.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.digitalcs.mcp.auth.AuthService;
import com.digitalcs.mcp.entity.Orders;
import com.digitalcs.mcp.mapper.OrdersMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrdersMapper ordersMapper;
    private final AuthService authService;

    private Orders findByNo(String orderNo) {
        return ordersMapper.selectOne(
                new LambdaQueryWrapper<Orders>().eq(Orders::getOrderNo, orderNo));
    }

    /** 按订单号查询，仅当订单归属当前用户(userId)时返回详情，否则拒绝。 */
    public Map<String, Object> queryByOrderNo(String orderNo, Long userId) {
        Orders order = findByNo(orderNo);
        if (order == null) {
            return Map.of("found", false, "message", "未找到订单: " + orderNo);
        }
        if (!authService.owns(userId, order.getCustomerId())) {
            return authService.deny("无权查看该订单(订单不属于当前用户): " + orderNo);
        }
        // 订单已自带 items / logistics / afterSales
        return Map.of("found", true, "order", order);
    }

    /** 列出当前用户名下订单(自助模式：只能看自己的)，按时间倒序。 */
    public Map<String, Object> listMyOrders(Long userId) {
        if (userId == null) {
            return authService.deny("缺少用户身份，无法查询订单");
        }
        List<Orders> orders = ordersMapper.selectList(
                new LambdaQueryWrapper<Orders>()
                        .eq(Orders::getCustomerId, userId)
                        .orderByDesc(Orders::getCreatedAt));
        return Map.of("authorized", true, "orders", orders);
    }

    /** 查订单物流，仅当订单归属当前用户(userId)时返回轨迹，否则拒绝。 */
    public Map<String, Object> trackLogistics(String orderNo, Long userId) {
        Orders order = findByNo(orderNo);
        if (order == null) {
            return Map.of("found", false, "message", "未找到订单: " + orderNo);
        }
        if (!authService.owns(userId, order.getCustomerId())) {
            return authService.deny("无权查看该订单物流(订单不属于当前用户): " + orderNo);
        }
        if (order.getLogistics() == null) {
            return Map.of("found", false, "message", "订单暂无发货记录: " + orderNo);
        }
        return Map.of("found", true, "logistics", order.getLogistics());
    }
}

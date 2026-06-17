package com.digitalcs.mcp.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.digitalcs.mcp.auth.AuthService;
import com.digitalcs.mcp.entity.Orders;
import com.digitalcs.mcp.entity.Product;
import com.digitalcs.mcp.mapper.OrdersMapper;
import com.digitalcs.mcp.mapper.ProductMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class OrderService {

    private static final DateTimeFormatter ORDER_NO_FORMATTER = DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSS");

    private final OrdersMapper ordersMapper;
    private final ProductMapper productMapper;
    private final ProductService productService;
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

    /** 创建待付款订单：确认后校验商品、价格和库存，扣减库存并写入订单。 */
    @Transactional
    public Map<String, Object> createOrder(
            Long userId,
            String productNo,
            Integer quantity,
            String spec,
            String receiverName,
            String receiverPhone,
            String receiverAddress) {
        if (userId == null) {
            return authService.deny("缺少用户身份，无法创建订单");
        }
        int count = quantity == null ? 0 : quantity;
        if (count <= 0) {
            return Map.of("found", true, "ok", false, "message", "购买数量必须大于 0");
        }

        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>().eq(Product::getProductNo, productNo));
        if (product == null) {
            return Map.of("found", false, "message", "未找到商品: " + productNo);
        }
        if (product.getStatus() == null || product.getStatus() != 1) {
            return Map.of("found", true, "ok", false, "message", "商品已下架，无法创建订单: " + productNo);
        }
        if (product.getStock() == null || product.getStock() < count) {
            return Map.of("found", true, "ok", false, "message", "商品库存不足，当前库存: " + (product.getStock() == null ? 0 : product.getStock()));
        }

        Map<String, Object> detail = productService.getDetail(productNo);
        Object rawPrice = detail.get("price");
        BigDecimal price = rawPrice instanceof BigDecimal
                ? (BigDecimal) rawPrice
                : parsePrice(rawPrice);
        if (price == null) {
            return Map.of("found", true, "ok", false, "message", "商品价格暂不可用，无法创建订单: " + productNo);
        }

        int updated = productMapper.update(
                null,
                new LambdaUpdateWrapper<Product>()
                        .eq(Product::getProductNo, productNo)
                        .ge(Product::getStock, count)
                        .setSql("stock = stock - " + count));
        if (updated <= 0) {
            return Map.of("found", true, "ok", false, "message", "商品库存不足，请重新确认后再提交");
        }

        Orders.Item item = new Orders.Item();
        item.setProductNo(productNo);
        item.setProductName(String.valueOf(detail.getOrDefault("name", product.getName())));
        item.setSpec(spec == null ? "" : spec.trim());
        item.setPrice(price);
        item.setQuantity(count);

        BigDecimal total = price.multiply(BigDecimal.valueOf(count));
        Orders order = new Orders();
        order.setOrderNo(nextOrderNo());
        order.setCustomerId(userId);
        order.setTotalAmount(total);
        order.setPayAmount(BigDecimal.ZERO);
        order.setOrderStatus(0);
        order.setPayStatus(0);
        order.setReceiverName(receiverName == null ? "" : receiverName.trim());
        order.setReceiverPhone(receiverPhone == null ? "" : receiverPhone.trim());
        order.setReceiverAddress(receiverAddress == null ? "" : receiverAddress.trim());
        order.setItems(List.of(item));
        order.setLogistics(null);
        ordersMapper.insert(order);
        return Map.of("authorized", true, "created", true, "ok", true, "order", order);
    }

    /** 撤销订单：仅「待付款」(orderStatus=0)的订单可由本人撤销，撤销后置为已取消(4)。 */
    @Transactional
    public Map<String, Object> cancelOrder(String orderNo, Long userId) {
        Orders order = findByNo(orderNo);
        if (order == null) {
            return Map.of("found", false, "message", "未找到订单: " + orderNo);
        }
        if (!authService.owns(userId, order.getCustomerId())) {
            return authService.deny("无权撤销该订单(订单不属于当前用户): " + orderNo);
        }
        if (order.getOrderStatus() == null || order.getOrderStatus() != 0) {
            return Map.of("found", true, "ok", false, "message", "仅待付款订单可撤销，当前订单状态不支持撤销");
        }
        order.setOrderStatus(4);
        ordersMapper.updateById(order);
        return Map.of("found", true, "ok", true, "order", order);
    }

    private String nextOrderNo() {
        return "O" + LocalDateTime.now().format(ORDER_NO_FORMATTER);
    }

    private BigDecimal parsePrice(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return new BigDecimal(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}

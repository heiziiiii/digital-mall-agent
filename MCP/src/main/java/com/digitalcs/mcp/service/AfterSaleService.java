package com.digitalcs.mcp.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.digitalcs.mcp.auth.AuthService;
import com.digitalcs.mcp.entity.AfterSale;
import com.digitalcs.mcp.entity.Orders;
import com.digitalcs.mcp.mapper.AfterSaleMapper;
import com.digitalcs.mcp.mapper.OrdersMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;

/**
 * 售后单服务：售后单的创建与查询。所有涉及个人数据的入口均做归属鉴权(自助模式：只能访问自己的售后)，
 * 创建时校验订单存在并回填客户，售后单作为独立表持久化。
 */
@Service
@RequiredArgsConstructor
public class AfterSaleService {

    private final AfterSaleMapper afterSaleMapper;
    private final OrdersMapper ordersMapper;
    private final AuthService authService;
    private final DateTimeFormatter afterSaleNoFormatter;

    /** 按售后单号查询，未找到返回 null。 */
    private AfterSale findByNo(String afterSaleNo) {
        return afterSaleMapper.selectOne(
                new LambdaQueryWrapper<AfterSale>().eq(AfterSale::getAfterSaleNo, afterSaleNo));
    }

    /** 按售后单号查询，仅当售后单归属当前用户(userId)时返回，否则拒绝。 */
    public Map<String, Object> queryByNo(String afterSaleNo, Long userId) {
        AfterSale as = findByNo(afterSaleNo);
        if (as == null) {
            return Map.of("found", false, "message", "未找到售后单: " + afterSaleNo);
        }
        if (!authService.owns(userId, as.getCustomerId())) {
            return authService.deny("无权查看该售后单(售后单不属于当前用户): " + afterSaleNo);
        }
        return Map.of("found", true, "afterSale", as);
    }

    /** 查询某订单的全部售后单，仅当该订单归属当前用户(userId)时返回，否则拒绝。 */
    public Map<String, Object> listByOrderNo(String orderNo, Long userId) {
        Orders order = ordersMapper.selectOne(
                new LambdaQueryWrapper<Orders>().eq(Orders::getOrderNo, orderNo));
        if (order == null) {
            return Map.of("found", false, "message", "未找到订单: " + orderNo);
        }
        if (!authService.owns(userId, order.getCustomerId())) {
            return authService.deny("无权查看该订单的售后记录(订单不属于当前用户): " + orderNo);
        }
        List<AfterSale> list = afterSaleMapper.selectList(
                new LambdaQueryWrapper<AfterSale>()
                        .eq(AfterSale::getOrderNo, orderNo)
                        .orderByDesc(AfterSale::getCreatedAt));
        return Map.of("authorized", true, "afterSales", list);
    }

    /** 查询当前用户名下的全部售后单(自助模式：只能看自己的)。 */
    public Map<String, Object> listMyAfterSales(Long userId) {
        if (userId == null) {
            return authService.deny("缺少用户身份，无法查询售后");
        }
        List<AfterSale> list = afterSaleMapper.selectList(
                new LambdaQueryWrapper<AfterSale>()
                        .eq(AfterSale::getCustomerId, userId)
                        .orderByDesc(AfterSale::getCreatedAt));
        return Map.of("authorized", true, "afterSales", list);
    }

    /** 为订单创建售后单：先校验订单归属当前用户(userId)，再校验订单存在并回填客户，初始状态为待审(0)。 */
    @Transactional
    public Map<String, Object> create(String orderNo, Long userId, Integer type, String reason) {
        Orders order = ordersMapper.selectOne(
                new LambdaQueryWrapper<Orders>().eq(Orders::getOrderNo, orderNo));
        if (order == null) {
            return Map.of("found", false, "message", "订单不存在: " + orderNo);
        }
        if (!authService.owns(userId, order.getCustomerId())) {
            return authService.deny("无权对该订单发起售后(订单不属于当前用户): " + orderNo);
        }
        AfterSale as = new AfterSale();
        as.setAfterSaleNo(generateNo());
        as.setOrderNo(orderNo);
        as.setCustomerId(order.getCustomerId());
        as.setType(type);
        as.setReason(reason);
        as.setStatus(0);
        afterSaleMapper.insert(as);
        return Map.of("authorized", true, "created", true, "afterSale", as);
    }

    /** 撤销售后单：仅「待审核」(status=0)的售后单可由本人撤销，撤销即删除该申请记录。 */
    @Transactional
    public Map<String, Object> cancel(String afterSaleNo, Long userId) {
        AfterSale as = findByNo(afterSaleNo);
        if (as == null) {
            return Map.of("found", false, "message", "未找到售后单: " + afterSaleNo);
        }
        if (!authService.owns(userId, as.getCustomerId())) {
            return authService.deny("无权撤销该售后单(售后单不属于当前用户): " + afterSaleNo);
        }
        if (as.getStatus() == null || as.getStatus() != 0) {
            return Map.of("found", true, "ok", false, "message", "仅待审核的售后单可撤销，当前状态不支持撤销");
        }
        afterSaleMapper.deleteById(as.getId());
        return Map.of("found", true, "ok", true);
    }

    private String generateNo() {
        return "AS" + LocalDateTime.now().format(afterSaleNoFormatter);
    }
}

package com.digitalcs.mcp.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.digitalcs.mcp.auth.AuthService;
import com.digitalcs.mcp.entity.AfterSale;
import com.digitalcs.mcp.entity.HumanService;
import com.digitalcs.mcp.entity.Orders;
import com.digitalcs.mcp.mapper.AfterSaleMapper;
import com.digitalcs.mcp.mapper.HumanServiceMapper;
import com.digitalcs.mcp.mapper.OrdersMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

/**
 * 人工服务单服务：创建需人工客服介入的服务请求，并校验关联订单/售后归属。
 */
@Service
@RequiredArgsConstructor
public class HumanServiceService {

    private static final DateTimeFormatter SERVICE_NO_FORMATTER = DateTimeFormatter.ofPattern("yyyyMMddHHmmssSSS");

    private final HumanServiceMapper humanServiceMapper;
    private final OrdersMapper ordersMapper;
    private final AfterSaleMapper afterSaleMapper;
    private final AuthService authService;

    @Transactional
    public Map<String, Object> create(Long userId, String reason, String orderNo, String afterSaleNo) {
        if (userId == null) {
            return authService.deny("缺少用户身份，无法创建人工服务单");
        }
        if (reason == null || reason.trim().isEmpty()) {
            return Map.of("created", false, "message", "创建人工服务单前请填写原因");
        }

        Long customerId = userId;
        String normalizedOrderNo = normalize(orderNo);
        String normalizedAfterSaleNo = normalize(afterSaleNo);

        if (normalizedOrderNo != null) {
            Orders order = ordersMapper.selectOne(
                    new LambdaQueryWrapper<Orders>().eq(Orders::getOrderNo, normalizedOrderNo));
            if (order == null) {
                return Map.of("found", false, "message", "未找到订单: " + normalizedOrderNo);
            }
            if (!authService.owns(userId, order.getCustomerId())) {
                return authService.deny("无权为该订单创建人工服务单(订单不属于当前用户): " + normalizedOrderNo);
            }
            customerId = order.getCustomerId();
        }

        if (normalizedAfterSaleNo != null) {
            AfterSale afterSale = afterSaleMapper.selectOne(
                    new LambdaQueryWrapper<AfterSale>().eq(AfterSale::getAfterSaleNo, normalizedAfterSaleNo));
            if (afterSale == null) {
                return Map.of("found", false, "message", "未找到售后单: " + normalizedAfterSaleNo);
            }
            if (!authService.owns(userId, afterSale.getCustomerId())) {
                return authService.deny("无权为该售后单创建人工服务单(售后单不属于当前用户): " + normalizedAfterSaleNo);
            }
            customerId = afterSale.getCustomerId();
            if (normalizedOrderNo == null) {
                normalizedOrderNo = afterSale.getOrderNo();
            }
        }

        HumanService service = new HumanService();
        service.setServiceNo(generateNo());
        service.setCustomerId(customerId);
        service.setOrderNo(normalizedOrderNo);
        service.setAfterSaleNo(normalizedAfterSaleNo);
        service.setReason(reason.trim());
        service.setStatus(0);
        humanServiceMapper.insert(service);
        return Map.of("authorized", true, "created", true, "humanService", service);
    }

    private static String normalize(String value) {
        if (value == null || value.trim().isEmpty()) {
            return null;
        }
        return value.trim();
    }

    private String generateNo() {
        return "HS" + LocalDateTime.now().format(SERVICE_NO_FORMATTER);
    }
}

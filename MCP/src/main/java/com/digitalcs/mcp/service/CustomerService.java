package com.digitalcs.mcp.service;

import com.digitalcs.mcp.auth.AuthService;
import com.digitalcs.mcp.entity.Customer;
import com.digitalcs.mcp.mapper.CustomerMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.Map;

/**
 * 用户信息库服务：自助模式下只允许查询当前用户(userId)本人的资料。
 */
@Service
@RequiredArgsConstructor
public class CustomerService {

    private final CustomerMapper customerMapper;
    private final AuthService authService;

    /** 查询当前用户本人资料(自助模式：customerId 即 userId，不能查他人)。 */
    public Map<String, Object> getMyProfile(Long userId) {
        if (userId == null) {
            return authService.deny("缺少用户身份，无法查询资料");
        }
        Customer customer = customerMapper.selectById(userId);
        if (customer == null) {
            return Map.of("found", false, "message", "未找到客户(客户ID: " + userId + ")");
        }
        return Map.of("authorized", true, "found", true, "customer", customer);
    }
}

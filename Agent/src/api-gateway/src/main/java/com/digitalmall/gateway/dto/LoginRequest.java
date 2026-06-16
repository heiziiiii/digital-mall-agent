package com.digitalmall.gateway.dto;

/**
 * 登录请求体。
 *
 * @param phone    手机号
 * @param password 登录密码
 */
public record LoginRequest(
        String phone,
        String password
) {
}

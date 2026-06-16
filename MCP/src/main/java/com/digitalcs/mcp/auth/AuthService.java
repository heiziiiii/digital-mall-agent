package com.digitalcs.mcp.auth;

import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 自助模式鉴权：操作者(userId)只能访问/操作归属于自己的数据。
 * 仅做「数据归属」校验，不验证身份真伪——userId 的真实性应由上游会话/网关保证，
 * 本服务假定传入的 userId 即当前登录客户本人。
 */
@Component
public class AuthService {

    /** 操作者是否为资源归属客户本人。userId 为空视为未鉴权，一律拒绝。 */
    public boolean owns(Long userId, Long ownerCustomerId) {
        return userId != null && userId.equals(ownerCustomerId);
    }

    /** 统一的「无权访问」返回体，供工具直接回给大模型，便于其礼貌告知客户。 */
    public Map<String, Object> deny(String message) {
        return Map.of("authorized", false, "message", message);
    }
}

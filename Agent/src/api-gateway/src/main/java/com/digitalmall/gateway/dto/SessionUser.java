package com.digitalmall.gateway.dto;

/**
 * 会话中的已登录用户信息，序列化为 JSON 后存入 Redis，并透传给下游 Agent 服务。
 *
 * @param customerId  客户数据库主键 ID
 * @param customerNo  客户编号
 * @param nickname    昵称
 * @param memberLevel 会员等级
 */
public record SessionUser(
        Long customerId,
        String customerNo,
        String nickname,
        Integer memberLevel
) {
}

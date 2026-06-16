package com.digitalcs.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户信息库（MySQL 权威）：客服侧的客户基础资料。
 */
@Data
@TableName("customer")
public class Customer {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String customerNo;
    private String nickname;
    private String phone;
    /** 测试登录密码；生产环境应存储哈希值。 */
    private String password;
    /** 0普通 1银 2金 3铂金 */
    private Integer memberLevel;
    private LocalDateTime createdAt;
}

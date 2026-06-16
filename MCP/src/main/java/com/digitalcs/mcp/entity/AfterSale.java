package com.digitalcs.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 售后单。由原「客服会话表」改造而来：售后不再折叠在订单 JSON 里，而是作为独立业务表，
 * 一笔售后对应一条记录，关联订单号与客户。
 */
@Data
@TableName("after_sale")
public class AfterSale {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String afterSaleNo;
    /** 关联订单号 */
    private String orderNo;
    private Long customerId;
    /** 1退货退款 2换货 3仅退款 4维修 */
    private Integer type;
    private String reason;
    /** 0待审 1已通过 2已拒绝 3处理中 4已完成 */
    private Integer status;
    /** 处理备注 */
    private String remark;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

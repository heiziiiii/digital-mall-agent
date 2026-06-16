package com.digitalcs.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 人工服务单。与售后单分离，用于记录需要人工客服介入的服务请求。
 */
@Data
@TableName("human_service")
public class HumanService {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String serviceNo;
    private Long customerId;
    /** 关联订单号，可为空 */
    private String orderNo;
    /** 关联售后单号，可为空 */
    private String afterSaleNo;
    private String reason;
    /** 0待处理 1处理中 2已完成 3已关闭 */
    private Integer status;
    /** 处理备注 */
    private String remark;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

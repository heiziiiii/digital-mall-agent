package com.digitalcs.mcp.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 商品库存库（MySQL 权威）。纯库存表：只保留库存等交易必需字段；
 * 价格/发布时间/副标题/分类/品牌/描述/规格参数等「详细信息」存于 Qdrant，按 productNo 关联。
 */
@Data
@TableName("product")
public class Product {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String productNo;
    private String name;
    private Integer stock;
    /** 0下架 1在售 */
    private Integer status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    @TableLogic
    private Integer deleted;
}

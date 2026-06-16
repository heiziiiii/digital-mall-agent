package com.digitalcs.mcp.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 订单。订单明细、物流轨迹折叠为 JSON 列；售后已独立为 {@link AfterSale} 表，不再挂在订单上。
 */
@Data
@TableName(value = "orders", autoResultMap = true)
public class Orders {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String orderNo;
    private Long customerId;
    private BigDecimal totalAmount;
    private BigDecimal payAmount;
    /** 0待付款 1待发货 2待收货 3已完成 4已取消 */
    private Integer orderStatus;
    /** 0未付 1已付 2已退款 */
    private Integer payStatus;
    private String receiverName;
    private String receiverPhone;
    private String receiverAddress;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private List<Item> items;
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Logistics logistics;

    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    @Data
    public static class Item {
        private String productNo;
        private String productName;
        private String spec;
        private BigDecimal price;
        private Integer quantity;
    }

    @Data
    public static class Logistics {
        private String company;
        private String trackingNo;
        /** 0待发 1已发 2运输中 3已签收 4异常 */
        private Integer status;
        private List<Trace> traces;
    }

    @Data
    public static class Trace {
        private String time;
        private String location;
        private String description;
    }
}

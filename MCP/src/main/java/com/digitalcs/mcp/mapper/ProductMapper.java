package com.digitalcs.mcp.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.digitalcs.mcp.entity.Product;

/** 商品库存库数据访问：检索已全部交给 Qdrant，本 Mapper 仅做按 productNo 取库存价格的条件查询。 */
public interface ProductMapper extends BaseMapper<Product> {
}

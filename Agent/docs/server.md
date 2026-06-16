# Docker 服务器配置

供后端其他应用连接本项目 docker-compose 拉起的服务（宿主机映射端口）。

## MySQL

| 项 | 值 |
| --- | --- |
| Host | localhost |
| Port | 3307 |
| Database | digital_cs |
| Username | root |
| Password | root |
| 字符集 | utf8mb4 / utf8mb4_unicode_ci |

JDBC URL：

```text
jdbc:mysql://localhost:3307/digital_cs?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
```

### 用户信息表 `customer`

| 字段 | 类型 | 约束/默认 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| customer_no | VARCHAR(32) | NOT NULL, UNIQUE | 客户编号 |
| nickname | VARCHAR(64) | 可空 | 昵称 |
| phone | VARCHAR(20) | 可空, KEY | 手机号 |
| password | VARCHAR(128) | NOT NULL, 默认 `123456` | 登录密码（测试环境明文） |
| member_level | TINYINT | NOT NULL, 默认 0 | 会员等级：0普通 1银 2金 3铂金 |
| created_at | DATETIME | NOT NULL, 默认当前时间 | 创建时间 |

## Redis

| 项 | 值 |
| --- | --- |
| Host | localhost |
| Port | 6379 |
| 密码 | 无 |

## Qdrant（向量库）

| 项 | 值 |
| --- | --- |
| Host | localhost |
| REST 端口 | 6333 |
| gRPC 端口 | 6334 |

> 若调用方也运行在同一 docker-compose 网络内，请改用服务名 + 容器内端口：
> `mysql:3306`、`redis:6379`、`qdrant:6333(REST)/6334(gRPC)`。

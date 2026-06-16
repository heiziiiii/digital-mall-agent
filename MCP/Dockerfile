# ===== 构建阶段：用 Maven + JDK17 编译打包 =====
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build

# 阿里云镜像配置，替代海外中央仓库，国内拉依赖快几十倍
COPY settings.xml /root/.m2/settings.xml

# 先单独拷贝 pom.xml 拉依赖，利用 Docker 层缓存，源码变动时不必重新下载依赖
COPY pom.xml .
RUN mvn -B dependency:go-offline

# 再拷贝源码并打包（跳过测试，测试依赖外部中间件）
# lombok.config 让 @Value 注解保留到生成的构造器上，须一并拷贝
COPY lombok.config .
COPY src ./src
RUN mvn -B clean package -DskipTests

# ===== 运行阶段：仅保留 JRE + 可执行 jar，镜像更小 =====
FROM eclipse-temurin:17-jre
WORKDIR /app

# 以非 root 用户运行，降低风险
RUN useradd -r -u 1001 appuser
COPY --from=build /build/target/*.jar app.jar
USER appuser

# MCP 服务器（WebMVC SSE）监听端口
EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]

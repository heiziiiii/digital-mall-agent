package com.digitalcs.mcp.web;

/**
 * 对外 REST 统一响应体。{@code code} 为 0 表示成功，非 0 表示业务/鉴权错误。
 * 与网关 {@code ApiResult} 保持同一结构，前端可统一按 {@code code===0} 解包。
 *
 * @param code    状态码（0=成功，403=无权访问，404=未找到 等）
 * @param message 提示信息
 * @param data    业务数据
 */
public record ApiResponse<T>(int code, String message, T data) {

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(0, "ok", data);
    }

    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null);
    }
}

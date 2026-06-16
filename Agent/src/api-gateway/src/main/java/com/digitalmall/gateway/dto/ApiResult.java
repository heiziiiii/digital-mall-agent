package com.digitalmall.gateway.dto;

/**
 * 统一响应体。{@code code} 为 0 表示成功，非 0 表示业务/鉴权错误。
 *
 * @param code    状态码（0=成功，401=未授权 等）
 * @param message 提示信息
 * @param data    业务数据
 */
public record ApiResult<T>(
        int code,
        String message,
        T data
) {
    public static <T> ApiResult<T> ok(T data) {
        return new ApiResult<>(0, "ok", data);
    }

    public static <T> ApiResult<T> error(int code, String message) {
        return new ApiResult<>(code, message, null);
    }
}

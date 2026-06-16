package com.digitalcs.mcp.tools;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;
import java.lang.reflect.Method;

/**
 * MCP 工具调用日志切面：统一拦截所有标注 {@link org.springframework.ai.tool.annotation.Tool}
 * 的方法，打印工具名、入参、返回结果与耗时，便于排查大模型的工具调用过程。
 */
@Aspect
@Component
public class ToolLoggingAspect {

    private static final Logger log = LoggerFactory.getLogger(ToolLoggingAspect.class);

    /** 返回结果过长时截断，避免日志被大列表/大文本刷屏。 */
    private static final int MAX_RESULT_LEN = 2000;

    @PostConstruct
    public void init() {
        log.info("【MCP工具调用】工具日志切面已加载，将拦截所有 @Tool 方法");
    }

    @Around("@annotation(org.springframework.ai.tool.annotation.Tool)")
    public Object logToolCall(ProceedingJoinPoint pjp) throws Throwable {
        MethodSignature signature = (MethodSignature) pjp.getSignature();
        Method method = signature.getMethod();
        String tool = method.getDeclaringClass().getSimpleName() + "." + method.getName();

        log.info("【MCP工具调用】{} 入参: {}", tool, formatArgs(signature.getParameterNames(), pjp.getArgs()));
        long start = System.currentTimeMillis();
        try {
            Object result = pjp.proceed();
            log.info("【MCP工具调用】{} 完成, 耗时 {}ms, 返回: {}",
                    tool, System.currentTimeMillis() - start, abbreviate(result));
            return result;
        } catch (Throwable e) {
            log.error("【MCP工具调用】{} 异常, 耗时 {}ms: {}",
                    tool, System.currentTimeMillis() - start, e.toString(), e);
            throw e;
        }
    }

    /** 把入参拼成 "名=值" 形式；参数名缺失时退化为 argN。 */
    private static String formatArgs(String[] names, Object[] args) {
        if (args == null || args.length == 0) {
            return "(无)";
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < args.length; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(names != null && i < names.length ? names[i] : "arg" + i)
                    .append('=').append(args[i]);
        }
        return sb.toString();
    }

    private static String abbreviate(Object result) {
        String s = String.valueOf(result);
        return s.length() > MAX_RESULT_LEN ? s.substring(0, MAX_RESULT_LEN) + "...(已截断)" : s;
    }
}

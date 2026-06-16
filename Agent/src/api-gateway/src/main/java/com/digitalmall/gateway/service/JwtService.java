package com.digitalmall.gateway.service;

import com.digitalmall.gateway.config.JwtProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;

/**
 * JWT 签发与解析服务（HS256 对称密钥，自签自验）。
 *
 * <p>token 中携带：sub=客户编号、customerId、nickname、memberLevel；并带 jti（用于登出黑名单）、
 * iss/iat/exp 标准声明。
 */
@Service
public class JwtService {

    private final SecretKey key;
    private final JwtProperties props;

    public JwtService(JwtProperties props) {
        this.props = props;
        // HS256 要求密钥长度 >= 256bit（32 字节），不足会在此抛异常，提醒尽早配置正确密钥
        this.key = Keys.hmacShaKeyFor(props.secret().getBytes(StandardCharsets.UTF_8));
    }

    /**
     * 签发 token。
     *
     * @return 包含 token 字符串与 jti、过期时间的结果
     */
    public IssuedToken issue(Long customerId, String customerNo, String nickname, Integer memberLevel) {
        Instant now = Instant.now();
        Instant exp = now.plus(props.ttl());
        String jti = UUID.randomUUID().toString();
        String token = Jwts.builder()
                .id(jti)
                .issuer(props.issuer())
                .subject(customerNo)
                .claim("customerId", customerId)
                .claim("nickname", nickname)
                .claim("memberLevel", memberLevel)
                .issuedAt(Date.from(now))
                .expiration(Date.from(exp))
                .signWith(key)
                .compact();
        return new IssuedToken(token, jti, exp, props.ttl().getSeconds());
    }

    /**
     * 解析并校验 token（验签 + 校验过期）。
     *
     * @throws io.jsonwebtoken.JwtException 签名无效、已过期或格式错误时抛出
     */
    public Claims parse(String token) {
        return Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    /** 签发结果。 */
    public record IssuedToken(String token, String jti, Instant expiresAt, long expiresInSeconds) {
    }
}

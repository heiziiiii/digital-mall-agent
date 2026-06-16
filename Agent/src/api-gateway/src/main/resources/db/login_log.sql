CREATE TABLE IF NOT EXISTS login_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account VARCHAR(64) NULL,
    customer_id BIGINT NULL,
    customer_no VARCHAR(64) NULL,
    ip_address VARCHAR(64) NULL,
    user_agent VARCHAR(512) NULL,
    status VARCHAR(16) NOT NULL,
    failure_reason VARCHAR(128) NULL,
    token_jti VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_login_log_account_created_at (account, created_at),
    INDEX idx_login_log_customer_created_at (customer_id, created_at),
    INDEX idx_login_log_status_created_at (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

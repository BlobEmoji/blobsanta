-- TODO: this

CREATE TABLE IF NOT EXISTS user_data (
    user_id BIGINT PRIMARY KEY,

    nickname VARCHAR(32) NOT NULL,

    UNIQUE(nickname),

    gifts_sent INT DEFAULT 0,

    gifts_received INT DEFAULT 0,

    last_gift TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gifts (
    id SERIAL PRIMARY KEY,
    
    user_id BIGINT NOT NULL REFERENCES user_data ON DELETE CASCADE,

    target_user_id BIGINT NOT NULL REFERENCES user_data ON DELETE CASCADE,

    active BOOLEAN DEFAULT true,
    
    activated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

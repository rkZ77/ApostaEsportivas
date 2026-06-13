-- Confirmação de e-mail
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(64);
-- Usuários existentes já são considerados verificados
UPDATE users SET email_verified = true WHERE email_verified = false;

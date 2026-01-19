-- migrate:up
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
  user_id VARCHAR(24) NOT NULL,
  department VARCHAR(100),
  question TEXT NOT NULL,
  response TEXT NOT NULL,
  followup_question TEXT,
  followup_response TEXT,
  feedback_type VARCHAR(20),
  feedback_reasons TEXT,
  idcc VARCHAR(20),
  model_name VARCHAR(100),
  created_at TIMESTAMPTZ DEFAULT NOW (),
  updated_at TIMESTAMPTZ DEFAULT NOW ()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations (user_id);

CREATE INDEX IF NOT EXISTS idx_conversations_department ON conversations (department);

CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations (created_at DESC);

-- migrate:down
DROP TABLE IF EXISTS conversations;

-- "Diriez-vous que la réponse de l'assistant IA vous a fait gagner du temps ?"
-- Asked at random after an answer, at most once per conversation:
-- 'yes', 'no' or 'dont_know' (NULL when not asked or not answered)
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS time_saved VARCHAR(20) DEFAULT NULL;

-- NPS: "Recommanderiez-vous l'assistant IA à un collègue ?" (0 to 10),
-- shown once per browser in a modal
CREATE TABLE IF NOT EXISTS nps_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
  user_id VARCHAR(24) NOT NULL,
  department VARCHAR(100),
  score SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 10),
  display_trigger VARCHAR(20),
  created_at TIMESTAMPTZ DEFAULT NOW ()
);

CREATE INDEX IF NOT EXISTS idx_nps_responses_created_at ON nps_responses (created_at DESC);

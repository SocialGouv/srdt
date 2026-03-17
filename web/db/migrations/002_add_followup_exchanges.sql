-- Add followup_exchanges JSONB column for storing multiple follow-up exchanges
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS followup_exchanges JSONB DEFAULT NULL;

-- Migrate existing data from followup_question/followup_response to new format
UPDATE conversations
SET followup_exchanges = jsonb_build_array(
  jsonb_build_object(
    'question', followup_question,
    'response', followup_response,
    'created_at', COALESCE(updated_at, NOW())
  )
)
WHERE followup_question IS NOT NULL
  AND followup_response IS NOT NULL
  AND followup_exchanges IS NULL;

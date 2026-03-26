-- Add followup_count column to track the number of follow-up exchanges per conversation
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS followup_count INTEGER DEFAULT 0;

-- Backfill existing data from followup_exchanges JSONB array
UPDATE conversations
SET followup_count = jsonb_array_length(followup_exchanges)
WHERE followup_exchanges IS NOT NULL
  AND followup_count = 0;

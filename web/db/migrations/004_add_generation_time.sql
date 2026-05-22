-- Add generation_time_ms column to track response generation duration (initial question)
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS generation_time_ms INTEGER DEFAULT NULL;

-- Ensure existing follow-up exchanges expose a generation_time_ms field (null-backfilled)
UPDATE conversations
SET followup_exchanges = (
  SELECT jsonb_agg(
    CASE
      WHEN exchange ? 'generation_time_ms' THEN exchange
      ELSE exchange || jsonb_build_object('generation_time_ms', NULL)
    END
  )
  FROM jsonb_array_elements(followup_exchanges) AS exchange
)
WHERE followup_exchanges IS NOT NULL
  AND jsonb_array_length(followup_exchanges) > 0;

-- Frozen from pre-v0.3.34 history; legacy source ledgers are retained for verified export.

ALTER TABLE llm_conversation_session_index
ADD COLUMN sequence_number INTEGER NOT NULL DEFAULT 0;

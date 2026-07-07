-- Record which SMS provider delivered a send_sms job (CLAUDE.md §9:
-- "record which provider succeeded on the job row"). Nullable: only send_sms
-- jobs set it, and only on success.
ALTER TABLE jobs ADD COLUMN provider            TEXT;
ALTER TABLE jobs ADD COLUMN provider_message_id TEXT;

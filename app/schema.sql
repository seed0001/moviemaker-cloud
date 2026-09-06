-- moviemaker-cloud schema. Applied idempotently on boot (CREATE TABLE IF NOT EXISTS everywhere).

CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'Untitled episode',
  premise TEXT NOT NULL DEFAULT '',
  style TEXT NOT NULL DEFAULT '',
  scene_order TEXT[] NOT NULL DEFAULT '{}',
  is_active BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_episode ON episodes ((true)) WHERE is_active;

CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  reference_image_job_id TEXT,
  reference_image_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS locations (
  id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  reference_image_job_id TEXT,
  reference_image_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenes (
  id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT 'dialogue',
  duration INTEGER NOT NULL DEFAULT 5,
  resolution TEXT NOT NULL DEFAULT '720p',
  aspect_ratio TEXT NOT NULL DEFAULT '16:9',
  chain BOOLEAN NOT NULL DEFAULT false,
  character_ids TEXT[] NOT NULL DEFAULT '{}',
  location_id TEXT REFERENCES locations(id) ON DELETE SET NULL,
  prompt TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  approved_take_id TEXT,
  last_error TEXT,
  video_model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- NULL means "use the pipeline's default video model" — added after the table already existed
-- on Railway, so a plain CREATE TABLE IF NOT EXISTS above wouldn't reach deployed databases.
ALTER TABLE scenes ADD COLUMN IF NOT EXISTS video_model TEXT;

CREATE TABLE IF NOT EXISTS storyboard_panels (
  id TEXT PRIMARY KEY,
  scene_id TEXT NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
  job_id TEXT,
  prompt TEXT NOT NULL,
  reference_image_paths TEXT[] NOT NULL DEFAULT '{}',
  image_path TEXT,
  is_selected BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_threads (
  id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  scene_id TEXT REFERENCES scenes(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT 'anthropic/claude-sonnet-4.5',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS one_planning_thread ON chat_threads (episode_id) WHERE scene_id IS NULL;

CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT,
  tool_calls JSONB,
  tool_call_id TEXT,
  is_synthetic BOOLEAN NOT NULL DEFAULT false,
  seq BIGSERIAL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_messages_thread_seq ON chat_messages (thread_id, seq);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  phase TEXT,
  request_payload JSONB NOT NULL,
  result_payload JSONB,
  provider_job_id TEXT,
  polling_url TEXT,
  estimated_cost NUMERIC(10,4),
  actual_cost NUMERIC(10,4),
  pricing_source TEXT,
  attempt_number INTEGER NOT NULL DEFAULT 1,
  retry_of_job_id TEXT REFERENCES jobs(id),
  error TEXT,
  media_deleted_at TIMESTAMPTZ,
  episode_id TEXT REFERENCES episodes(id) ON DELETE CASCADE,
  scene_id TEXT REFERENCES scenes(id) ON DELETE CASCADE,
  character_id TEXT REFERENCES characters(id) ON DELETE CASCADE,
  location_id TEXT REFERENCES locations(id) ON DELETE CASCADE,
  panel_id TEXT REFERENCES storyboard_panels(id) ON DELETE CASCADE,
  thread_id TEXT REFERENCES chat_threads(id),
  triggering_tool_call_id TEXT,
  media_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status) WHERE status IN ('queued','in_progress');
CREATE INDEX IF NOT EXISTS jobs_thread ON jobs (thread_id);
-- both added after these tables already existed on Railway, so CREATE TABLE IF NOT EXISTS above
-- wouldn't reach deployed databases
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS media_deleted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS media_files (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  content_type TEXT NOT NULL,
  bytes INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_pricing_cache (
  model_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  pricing_json JSONB NOT NULL,
  source TEXT NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (model_id, kind)
);

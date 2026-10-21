CREATE TABLE IF NOT EXISTS runs (
  run_id UUID PRIMARY KEY,
  node_name TEXT NOT NULL,
  organization_name TEXT,
  chef_server_fqdn TEXT,
  status TEXT NOT NULL,
  start_time TIMESTAMPTZ,
  end_time TIMESTAMPTZ,
  received_at TIMESTAMPTZ NOT NULL,
  duration_ms BIGINT,
  total_resource_count INTEGER,
  updated_resource_count INTEGER,
  message_type TEXT,
  message_version TEXT,
  entity_uuid UUID,
  policy_name TEXT,
  policy_group TEXT,
  source TEXT,
  run_list JSONB,
  expanded_run_list JSONB,
  cookbooks JSONB,
  deprecations JSONB,
  raw_payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS runs_node_end_time_idx
  ON runs (node_name, end_time DESC);

CREATE INDEX IF NOT EXISTS runs_status_end_time_idx
  ON runs (status, end_time DESC);

CREATE TABLE IF NOT EXISTS resource_events (
  event_id BIGSERIAL PRIMARY KEY,
  run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  resource_id TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_name TEXT NOT NULL,
  status TEXT,
  result TEXT,
  duration_ms BIGINT,
  cookbook_name TEXT,
  cookbook_version TEXT,
  recipe_name TEXT,
  ignore_failure BOOLEAN,
  event_order INTEGER NOT NULL,
  before_state JSONB,
  after_state JSONB,
  delta JSONB,
  UNIQUE (run_id, resource_id, status, result, event_order)
);

CREATE INDEX IF NOT EXISTS resource_events_run_order_idx
  ON resource_events (run_id, event_order);

CREATE INDEX IF NOT EXISTS resource_events_cookbook_resource_idx
  ON resource_events (
    cookbook_name,
    resource_type,
    resource_name,
    status
  );

CREATE INDEX IF NOT EXISTS resource_events_recipe_idx
  ON resource_events (recipe_name);

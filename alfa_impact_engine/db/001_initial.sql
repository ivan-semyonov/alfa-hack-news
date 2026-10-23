-- Target persistence schema (stage M0/M1). Database is OPTIONAL in current synthetic API.
-- All identifiers belong to the synthetic domain. Hardening: auth and tenant RLS.
CREATE TABLE IF NOT EXISTS companies (
  id TEXT PRIMARY KEY,
  main_okved_code TEXT,
  main_okved_name TEXT,
  region TEXT,
  revenue_company NUMERIC,
  group_id TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS payment_edges (
  payer TEXT NOT NULL,
  beneficiary TEXT NOT NULL,
  pay_amt NUMERIC,
  pay_cnt INTEGER,
  period_start DATE,
  period_end DATE,
  data_source TEXT NOT NULL,
  PRIMARY KEY (payer, beneficiary, data_source),
  CHECK (pay_cnt IS NULL OR pay_cnt >= 0)
);
CREATE INDEX IF NOT EXISTS payment_beneficiary_idx ON payment_edges (beneficiary);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL,
  source_reference TEXT NOT NULL,
  statement TEXT,
  published_at TIMESTAMPTZ,
  retrieved_at TIMESTAMPTZ DEFAULT NOW(),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS graph_nodes (
  id TEXT PRIMARY KEY,
  company_id TEXT,
  node_type TEXT NOT NULL,
  label TEXT NOT NULL,
  knowledge_status TEXT NOT NULL CHECK (knowledge_status IN ('FACT','TEMPLATE','INFERENCE','HYPOTHESIS','REJECTED')),
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS graph_nodes_company_idx ON graph_nodes (company_id);
CREATE TABLE IF NOT EXISTS graph_edges (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES graph_nodes(id),
  target_id TEXT NOT NULL REFERENCES graph_nodes(id),
  relation TEXT NOT NULL,
  knowledge_status TEXT NOT NULL CHECK (knowledge_status IN ('FACT','TEMPLATE','INFERENCE','HYPOTHESIS','REJECTED')),
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS graph_edges_source_idx ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS graph_edges_target_idx ON graph_edges(target_id);
CREATE TABLE IF NOT EXISTS news_documents (
  id TEXT PRIMARY KEY,
  source_url TEXT,
  publisher TEXT,
  published_at TIMESTAMPTZ,
  content_hash TEXT NOT NULL UNIQUE,
  text_content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  event_type TEXT,
  title TEXT NOT NULL,
  event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS analysis_runs (
  id TEXT PRIMARY KEY,
  company_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  status TEXT NOT NULL,
  run_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS insights (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id),
  insight_data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Additional normalized tables and RLS policies are planned for M1/M2.

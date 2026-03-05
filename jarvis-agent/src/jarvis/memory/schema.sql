-- schema.sql
-- Base de datos SQLite para memoria persistente de Jarvis

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,         -- system/user/assistant/tool
  content TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS tool_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  tool_args TEXT NOT NULL,     -- JSON string
  tool_result TEXT NOT NULL,   -- JSON string
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

-- Índices para queries frecuentes (O(log n) en lugar de O(n))
CREATE INDEX IF NOT EXISTS idx_messages_session_id  ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at  ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_tool_events_session  ON tool_events(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_events_created  ON tool_events(created_at);
CREATE INDEX IF NOT EXISTS idx_tool_events_name     ON tool_events(tool_name);

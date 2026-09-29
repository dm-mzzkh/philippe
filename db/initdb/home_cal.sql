-- home_cal.sql — schema + seed for the home-cleaning calendar bot (PostgreSQL)
--
-- Safe to re-run: it drops everything and recreates it, so it doubles as a
-- "reset to clean" script for tests.  Run it with:
--   psql -U bot -d bot_dev -f home_cal.sql
-- or, in Docker:
--   docker compose exec -T db psql -U bot -d bot_dev < home_cal.sql

BEGIN;

-- Drop dependents first (logs references tasks), then the enum type.
DROP TABLE IF EXISTS workout_sets;
DROP TABLE IF EXISTS sleeps;
DROP TABLE IF EXISTS logs;
DROP TABLE IF EXISTS tasks;
DROP TYPE  IF EXISTS task_period;

-- period is a small fixed set -> native ENUM (cleaner than a CHECK constraint).
CREATE TYPE task_period AS ENUM ('day', 'week', 'month');

CREATE TABLE tasks (
  id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  title      TEXT        NOT NULL UNIQUE,
  period     task_period NOT NULL,
  every      INTEGER     NOT NULL DEFAULT 1 CHECK (every BETWEEN 1 AND 365),
  active     BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE logs (
  id        INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id   INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  done_at   DATE    NOT NULL DEFAULT CURRENT_DATE,
  comment   TEXT,
  user_id   BIGINT,            -- Telegram IDs exceed 2^31 -> must be BIGINT, not INTEGER
  user_name TEXT
);

CREATE INDEX idx_logs_task ON logs (task_id, done_at DESC);

-- Sleep diary: one row per night. start_at/end_at are clock times; a night that
-- crosses midnight has end_at <= start_at (the view adds 24h to get duration).
CREATE TABLE sleeps (
  id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sleep_date DATE        NOT NULL DEFAULT CURRENT_DATE,
  start_at   TIME        NOT NULL,
  end_at     TIME        NOT NULL,
  comment    TEXT,
  user_id    BIGINT,            -- Telegram IDs exceed 2^31 -> must be BIGINT, not INTEGER
  user_name  TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sleeps_date ON sleeps (sleep_date DESC);

-- Workout diary: one row per exercise (N sets × M reps @ weight). The exercise
-- name is free text; the form's select just suggests names logged before.
CREATE TABLE workout_sets (
  id           INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workout_date DATE         NOT NULL DEFAULT CURRENT_DATE,
  exercise     TEXT         NOT NULL,      -- free text; past entries just suggest it
  sets         INTEGER      NOT NULL CHECK (sets BETWEEN 1 AND 50),
  reps         INTEGER      NOT NULL CHECK (reps BETWEEN 1 AND 1000),
  weight       NUMERIC(6,2) CHECK (weight >= 0),   -- кг; NULL = bodyweight
  comment      TEXT,
  user_id      BIGINT,
  user_name    TEXT,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_workout_sets_date ON workout_sets (workout_date DESC);

-- ---------------------------------------------------------------------------
-- seed: tasks
-- ---------------------------------------------------------------------------
INSERT INTO tasks (title, period, every, active) VALUES
  ('пропылесосить',                    'day',   4, TRUE),
  ('влажная приборка',                 'month', 1, TRUE),
  ('отмыть конфорку',                  'month', 1, TRUE),
  ('помыть зеркала',                   'month', 1, TRUE),
  ('помыть кошкин туалет',             'month', 1, TRUE),
  ('помыть пол',                       'month', 1, TRUE),
  ('помыть холодильник',               'month', 3, TRUE),
  ('почистить посудомойку',            'month', 2, TRUE),
  ('почистить стиральную машину',      'month', 2, TRUE),
  ('прибрать лоджию',                  'month', 1, TRUE),
  ('отмыть микроволновку и плиту',     'week',  3, TRUE),
  ('поменять постельное бельё',        'week',  1, TRUE),
  ('помыть ванную, туалет и раковины', 'week',  2, TRUE),
  ('помыть увлажнитель',               'week',  3, TRUE);

-- ---------------------------------------------------------------------------
-- seed: logs
-- ---------------------------------------------------------------------------
INSERT INTO logs (task_id, done_at, comment, user_id, user_name)
SELECT t.id, v.done_at::date, v.comment::text, v.user_id, v.user_name
FROM (VALUES
  ('почистить стиральную машину', '2026-05-31', NULL, 5303609453, '@megadurachok'),
  ('помыть пол',                  '2026-05-31', NULL, 5303609453, '@megadurachok'),
  ('помыть кошкин туалет',        '2026-05-31', NULL, 5303609453, '@megadurachok'),
  ('помыть зеркала',              '2026-05-31', NULL,  908129046, '@stormmilka'),
  ('помыть холодильник',          '2026-06-05', NULL, 5303609453, '@megadurachok'),
  ('поменять постельное бельё',   '2026-06-06', NULL, 5303609453, '@megadurachok'),
  ('прибрать лоджию',             '2026-06-07', NULL,  908129046, '@stormmilka')
) AS v(title, done_at, comment, user_id, user_name)
JOIN tasks t ON t.title = v.title;

COMMIT;

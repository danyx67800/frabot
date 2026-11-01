-- FraBot schema. All timestamps are ISO-8601 UTC strings.

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_categories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    emoji               TEXT NOT NULL DEFAULT '🎫',
    description         TEXT NOT NULL DEFAULT '',
    discord_category_id TEXT,
    staff_role_ids      TEXT NOT NULL DEFAULT '[]',
    welcome_message     TEXT NOT NULL DEFAULT '',
    position            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      TEXT NOT NULL,
    channel_id    TEXT,
    user_id       TEXT NOT NULL,
    user_name     TEXT NOT NULL,
    category_id   INTEGER REFERENCES ticket_categories(id) ON DELETE SET NULL,
    category_name TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'open',
    claimed_by    TEXT,
    claimed_by_name TEXT,
    message_id    TEXT,
    created_at    TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    closed_at     TEXT,
    closed_by     TEXT,
    close_reason  TEXT,
    transcript    TEXT
);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(guild_id, user_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_channel ON tickets(channel_id);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL DEFAULT 'Generale',
    question   TEXT NOT NULL,
    options    TEXT NOT NULL,
    answer     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS economy (
    guild_id   TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    user_name  TEXT NOT NULL DEFAULT '',
    balance    INTEGER NOT NULL DEFAULT 0,
    last_daily TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS game_stats (
    guild_id TEXT NOT NULL,
    user_id  TEXT NOT NULL,
    user_name TEXT NOT NULL DEFAULT '',
    game     TEXT NOT NULL,
    wins     INTEGER NOT NULL DEFAULT 0,
    plays    INTEGER NOT NULL DEFAULT 0,
    coins    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, game)
);

CREATE TABLE IF NOT EXISTS twitch_streamers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    login              TEXT NOT NULL UNIQUE,
    display_name       TEXT NOT NULL DEFAULT '',
    channel_id         TEXT NOT NULL,
    mention_type       TEXT NOT NULL DEFAULT 'none',
    mention_role_id    TEXT,
    template           TEXT NOT NULL DEFAULT '',
    is_live            INTEGER NOT NULL DEFAULT 0,
    stream_id          TEXT,
    message_id         TEXT,
    message_channel_id TEXT,
    live_started_at    TEXT,
    announced          INTEGER NOT NULL DEFAULT 0,
    last_checked       TEXT,
    last_validated     TEXT,
    last_error         TEXT,
    not_found          INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL
);

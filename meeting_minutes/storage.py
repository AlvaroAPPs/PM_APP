import psycopg


def ensure_meeting_minutes_storage(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_minutes (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NULL REFERENCES projects(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            project_subject TEXT NULL,
            meeting_date DATE NULL,
            start_time TEXT NULL,
            end_time TEXT NULL,
            location TEXT NULL,
            phase TEXT NULL,
            language VARCHAR(2) NOT NULL DEFAULT 'es',
            albaran_number TEXT NULL,
            participants JSONB NOT NULL DEFAULT '[]'::jsonb,
            topic_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
            topics TEXT NULL,
            discussion TEXT NULL,
            decisions_actions TEXT NULL,
            planning_next_steps TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        ALTER TABLE meeting_minutes
        ADD COLUMN IF NOT EXISTS topic_blocks JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )

-- Feedback table
CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rating TEXT NOT NULL,
    category TEXT NOT NULL,
    comment TEXT DEFAULT '',
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    clerk_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now()
);

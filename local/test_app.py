import json
import sqlite3
import unittest
from unittest.mock import patch

import app


def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT);
    CREATE TABLE memories(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      content TEXT NOT NULL,
      importance INTEGER NOT NULL DEFAULT 5,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      access_count INTEGER NOT NULL DEFAULT 0,
      last_accessed_at TEXT
    );
    """)
    return conn


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return json.dumps({"choices": [{"message": {"content": self.body}}]}).encode()


class MemoryTests(unittest.TestCase):
    def test_retrieval_keeps_anchors_and_finds_relevant_memory(self):
        conn = test_db()
        memories = [
            ("User is allergic to peanuts", 10),
            ("User prefers dark mode", 9),
            ("The project database is PostgreSQL", 3),
            ("The garden has tomato plants", 2),
        ]
        for content, importance in memories:
            conn.execute(
                "INSERT INTO memories(content,importance,created_at,updated_at) VALUES(?,?,?,?)",
                (content, importance, "2026-01-01", "2026-01-01"),
            )

        selected = app.select_memories(conn, "What database does the project use?", limit=3)
        contents = {row["content"] for row in selected}

        self.assertIn("User is allergic to peanuts", contents)
        self.assertIn("User prefers dark mode", contents)
        self.assertIn("The project database is PostgreSQL", contents)
        self.assertNotIn("The garden has tomato plants", contents)

    def test_current_prompt_is_sent_once(self):
        conn = test_db()
        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode()))
            return FakeResponse("Acknowledged")

        with patch("app.urllib.request.urlopen", fake_urlopen):
            reply = app.chat(conn, "unique-current-message")

        self.assertEqual(reply, "Acknowledged")
        user_messages = [m for m in captured["messages"] if m["role"] == "user"]
        self.assertEqual(user_messages, [{"role": "user", "content": "unique-current-message"}])


if __name__ == "__main__":
    unittest.main()

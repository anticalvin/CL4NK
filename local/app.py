#!/usr/bin/env python3
import json, os, re, sqlite3, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DB_PATH = ROOT / "cl4nk.db"
PERSONALITY_PATH = REPO / "personality.md"
UI_PATH = ROOT / "index.html"
HOST = os.getenv("CL4NK_HOST", "127.0.0.1")
PORT = int(os.getenv("CL4NK_PORT", "4242"))
DEFAULT_BASE_URL = os.getenv("CL4NK_BASE_URL", "http://127.0.0.1:11434/v1")
DEFAULT_MODEL = os.getenv("CL4NK_MODEL", "llama3.2")

STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "being", "but", "can", "could", "did", "does", "doing", "for", "from", "had",
    "has", "have", "here", "how", "into", "its", "just", "like", "more", "not",
    "now", "only", "our", "out", "really", "should", "some", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "too", "was",
    "were", "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your"
}


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memories(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      content TEXT NOT NULL,
      importance INTEGER NOT NULL DEFAULT 5,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    """)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
    if "access_count" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0")
    if "last_accessed_at" not in columns:
        conn.execute("ALTER TABLE memories ADD COLUMN last_accessed_at TEXT")
    return conn


def setting(conn, key, fallback=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else fallback


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def personality():
    try:
        return PERSONALITY_PATH.read_text(encoding="utf-8")
    except Exception:
        return "You are CL4NK, a useful local-first robotic companion. Accuracy outranks character."


def tokens(text):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_-]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def select_memories(conn, query, limit=8):
    """Return a small mix of relevant memories and high-importance identity anchors."""
    rows = conn.execute(
        "SELECT id,content,importance,created_at,updated_at,access_count,last_accessed_at FROM memories"
    ).fetchall()
    if not rows:
        return []

    query_tokens = tokens(query)
    scored = []
    for row in rows:
        memory_tokens = tokens(row["content"])
        overlap = len(query_tokens & memory_tokens)
        coverage = overlap / max(1, len(query_tokens))
        specificity = overlap / max(1, len(memory_tokens))
        relevance = (coverage * 0.65) + (specificity * 0.35)
        score = relevance * 10 + (row["importance"] / 10)
        scored.append((score, overlap, row))

    # Keep a couple of high-importance memories in every prompt as identity anchors,
    # then fill the remaining budget with memories that actually match the turn.
    anchors = sorted(rows, key=lambda r: (r["importance"], r["updated_at"]), reverse=True)[:2]
    chosen = {r["id"]: r for r in anchors}
    for _, overlap, row in sorted(scored, key=lambda item: item[0], reverse=True):
        if len(chosen) >= limit:
            break
        if overlap:
            chosen[row["id"]] = row

    return list(chosen.values())


def memory_block(conn, query):
    rows = select_memories(conn, query)
    if not rows:
        return "No durable user memories are stored yet."
    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE memories SET access_count=access_count+1,last_accessed_at=? WHERE id IN ({placeholders})",
        (now(), *ids),
    )
    return "\n".join(f"- ({r['importance']}/10) {r['content']}" for r in rows)


def recent_messages(conn, limit=28):
    rows = conn.execute("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def chat(conn, user_text):
    base_url = setting(conn, "base_url", DEFAULT_BASE_URL).rstrip("/")
    model = setting(conn, "model", DEFAULT_MODEL)
    api_key = setting(conn, "api_key", "local")
    system = personality() + "\n\nRelevant durable memory supplied by the user:\n" + memory_block(conn, user_text)
    history = recent_messages(conn)
    messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_text}]
    payload = json.dumps({"model": model, "messages": messages, "temperature": 0.8, "stream": False}).encode()
    req = urllib.request.Request(base_url + "/chat/completions", data=payload, headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach local model server at {base_url}: {e}")
    except Exception as e:
        raise RuntimeError(f"Model response failed: {e}")


def state(conn):
    return {
      "settings": {
        "base_url": setting(conn, "base_url", DEFAULT_BASE_URL),
        "model": setting(conn, "model", DEFAULT_MODEL),
        "has_api_key": bool(setting(conn, "api_key", ""))
      },
      "messages": [dict(r) for r in conn.execute("SELECT id,role,content,created_at FROM messages ORDER BY id ASC").fetchall()],
      "memories": [dict(r) for r in conn.execute("SELECT id,content,importance,created_at,updated_at,access_count,last_accessed_at FROM memories ORDER BY importance DESC, updated_at DESC").fetchall()]
    }


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[CL4NK]", fmt % args)

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            with db() as conn: self.send_json(state(conn))
            return
        if self.path == "/api/export":
            with db() as conn:
                out = state(conn)
                out["format"] = "cl4nk.identity.v1"
                out["exported_at"] = now()
                self.send_json(out)
            return
        if self.path in ("/", "/index.html"):
            body = UI_PATH.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        self.send_error(404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode() or "{}")

    def do_POST(self):
        try:
            data = self.read_json()
            if self.path == "/api/chat":
                text = str(data.get("message", "")).strip()
                if not text: return self.send_json({"error":"Message is empty"}, 400)
                with db() as conn:
                    reply = chat(conn, text)
                    conn.execute("INSERT INTO messages(role,content,created_at) VALUES('user',?,?)", (text, now()))
                    conn.execute("INSERT INTO messages(role,content,created_at) VALUES('assistant',?,?)", (reply, now()))
                    conn.commit()
                    self.send_json({"reply": reply, "state": state(conn)})
                return
            if self.path == "/api/memory":
                content = str(data.get("content", "")).strip(); importance = max(1, min(10, int(data.get("importance", 5))))
                if not content: return self.send_json({"error":"Memory is empty"}, 400)
                with db() as conn:
                    t=now(); conn.execute("INSERT INTO memories(content,importance,created_at,updated_at) VALUES(?,?,?,?)", (content,importance,t,t)); conn.commit(); self.send_json(state(conn))
                return
            if self.path == "/api/settings":
                with db() as conn:
                    for key in ("base_url","model","api_key"):
                        if key in data: set_setting(conn,key,data[key])
                    conn.commit(); self.send_json(state(conn))
                return
            if self.path == "/api/import":
                if data.get("format") != "cl4nk.identity.v1": return self.send_json({"error":"Unsupported identity bundle"},400)
                with db() as conn:
                    conn.execute("DELETE FROM messages"); conn.execute("DELETE FROM memories")
                    for m in data.get("messages",[]): conn.execute("INSERT INTO messages(role,content,created_at) VALUES(?,?,?)", (m.get("role","user"),m.get("content",""),m.get("created_at",now())))
                    for m in data.get("memories",[]):
                        t=m.get("created_at",now()); conn.execute("INSERT INTO memories(content,importance,created_at,updated_at) VALUES(?,?,?,?)", (m.get("content",""),int(m.get("importance",5)),t,m.get("updated_at",t)))
                    for k,v in data.get("settings",{}).items():
                        if k in ("base_url","model"): set_setting(conn,k,v)
                    conn.commit(); self.send_json(state(conn))
                return
            self.send_error(404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def do_DELETE(self):
        try:
            parts=self.path.strip('/').split('/')
            if len(parts)==3 and parts[:2]==['api','memory']:
                with db() as conn: conn.execute("DELETE FROM memories WHERE id=?",(int(parts[2]),)); conn.commit(); self.send_json(state(conn))
                return
            if self.path == "/api/history":
                with db() as conn: conn.execute("DELETE FROM messages"); conn.commit(); self.send_json(state(conn))
                return
            self.send_error(404)
        except Exception as e: self.send_json({"error":str(e)},500)


def main():
    with db() as conn:
        if not setting(conn,"base_url"): set_setting(conn,"base_url",DEFAULT_BASE_URL)
        if not setting(conn,"model"): set_setting(conn,"model",DEFAULT_MODEL)
        conn.commit()
    print(f"CL4NK local runtime: http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__": main()

"""SQLite 대화·유지보수 기록과 복구 요청 중복 방지 저장소."""
import sqlite3
import json
import hashlib
import uuid
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "session.db"


class SqliteSessionStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(os.environ.get("IOT_DB_PATH", str(db_path))) if db_path == DB_PATH else Path(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " thread_id TEXT, role TEXT, content TEXT, created TEXT)"
        )
        self.conn.execute("""CREATE TABLE IF NOT EXISTS maintenance (
            id TEXT PRIMARY KEY, device_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
            summary TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, inspection_key TEXT UNIQUE)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS recovery_requests (
            request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, response TEXT,
            http_status INTEGER, state TEXT NOT NULL)""")
        self.conn.commit()

    def record_maintenance(self, device_id, kind, status, summary, evidence):
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        key = None
        if kind == "inspection":
            key = hashlib.sha256(json.dumps({"device_id": device_id, "data": evidence.get("data"),
                                             "assessment": evidence.get("assessment")}, sort_keys=True).encode()).hexdigest()
        record_id = uuid.uuid4().hex
        with self.conn:
            self.conn.execute("""INSERT INTO maintenance VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(inspection_key) DO UPDATE SET status=excluded.status,
                summary=excluded.summary, evidence=excluded.evidence, updated_at=excluded.updated_at""",
                (record_id, device_id, kind, status, summary, json.dumps(evidence, ensure_ascii=False), now, now, key))
        if key:
            record_id = self.conn.execute("SELECT id FROM maintenance WHERE inspection_key=?", (key,)).fetchone()[0]
        return record_id

    def maintenance_history(self, device_id=None, limit=20):
        sql = "SELECT id,device_id,kind,status,summary,evidence,created_at,updated_at FROM maintenance"
        args = []
        if device_id:
            sql += " WHERE device_id=?"
            args.append(device_id)
        sql += " ORDER BY updated_at DESC, rowid DESC LIMIT ?"
        args.append(max(1, min(limit, 100)))
        return [dict(zip(("id","device_id","kind","status","summary","evidence","created_at","updated_at"),
                         (*row[:5], json.loads(row[5]), *row[6:]))) for row in self.conn.execute(sql, args)]

    def reserve_recovery(self, request_id, payload):
        serialized = json.dumps(payload, sort_keys=True)
        with self.conn:
            row = self.conn.execute("SELECT payload,response,http_status,state FROM recovery_requests WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[0] != serialized:
                    return {"http_status": 409, "body": {"detail": "다른 요청에 사용한 request_id입니다."}}
                if row[3] != "done":
                    return {"http_status": 409, "body": {"detail": "이전 요청의 실행 여부를 확인해야 합니다. 자동 재실행하지 않습니다."}}
                return {"http_status": row[2], "body": json.loads(row[1])}
            self.conn.execute("INSERT INTO recovery_requests(request_id,payload,state) VALUES(?,?,?)", (request_id, serialized, "pending"))
        return None

    def finish_recovery(self, request_id, body, http_status=200):
        with self.conn:
            self.conn.execute("UPDATE recovery_requests SET response=?,http_status=?,state='done' WHERE request_id=?",
                              (json.dumps(body, ensure_ascii=False), http_status, request_id))

    def append(self, thread_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?)",
            (thread_id, role, content, datetime.now().isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

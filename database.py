import sqlite3
import os
import sys
import time
from datetime import datetime

# === 核心配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "music_logs.db")


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """强制初始化表结构"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS api_logs
                     (
                         id
                         INTEGER
                         PRIMARY
                         KEY
                         AUTOINCREMENT,
                         timestamp
                         TEXT,
                         action_type
                         TEXT,
                         detail
                         TEXT,
                         status
                         TEXT,
                         api_response
                         TEXT,
                         duration_ms
                         INTEGER
                         DEFAULT
                         0
                     )''')
        conn.commit()
        conn.close()
        print(f"✅ 数据库初始化成功: {DB_FILE}")
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")


def insert_log(action_type, detail, status, api_response="", duration_ms=0):
    """写入日志"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        resp_str = str(api_response)[:500]

        c.execute(
            "INSERT INTO api_logs (timestamp, action_type, detail, status, api_response, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, action_type, detail, status, resp_str, duration_ms))
        conn.commit()
        conn.close()

        # === 这里的判断逻辑改成了中文 ===
        # 如果包含这些负面关键词，视为错误，打印详细信息
        if status in ["报错", "失败", "无结果", "Exception", "Failed"]:
            print(f"[{timestamp}] ❌ {action_type}: {status} - {api_response} ({duration_ms}ms)")
        else:
            print(f"[{timestamp}] ✅ {action_type}: {status} ({duration_ms}ms)")

        sys.stdout.flush()
        return True
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            print("⚠️ 检测到表丢失，正在自动重建...")
            init_db()
            return insert_log_retry(action_type, detail, status, api_response, duration_ms)
        return False
    except Exception as e:
        print(f"写入日志出错: {e}")
        return False


def insert_log_retry(action_type, detail, status, api_response, duration_ms):
    """重试写入"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        resp_str = str(api_response)[:500]
        c.execute(
            "INSERT INTO api_logs (timestamp, action_type, detail, status, api_response, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, action_type, detail, status, resp_str, duration_ms))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def fetch_logs(limit=30):
    """获取日志"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, timestamp, action_type, detail, status, duration_ms, api_response FROM api_logs ORDER BY id DESC LIMIT ?",
            (limit,))
        rows = c.fetchall()
        conn.close()

        data = []
        for row in rows:
            data.append({
                "id": row['id'],
                "time": row['timestamp'].split(' ')[1] if ' ' in row['timestamp'] else row['timestamp'],
                "type": row['action_type'],
                "detail": row['detail'],
                "status": row['status'],
                "duration": row['duration_ms'],
                "response": row['api_response']
            })
        return data
    except sqlite3.OperationalError:
        init_db()
        return []
    except Exception:
        return []


def clear_all_logs():
    """清空所有日志"""
    try:
        conn = get_db_connection()
        conn.execute("DELETE FROM api_logs")
        conn.commit()
        conn.close()
        return True
    except Exception:
        init_db()
        return True

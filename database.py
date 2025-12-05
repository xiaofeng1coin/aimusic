import sqlite3
import os
import sys
import re
from datetime import datetime

# === 核心配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "music_logs.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def check_and_fix_schema(conn):
    """
    智能修复数据库结构：
    1. 创建缺失的表
    2. 检查现有表是否缺少关键字段（自动迁移）
    """
    c = conn.cursor()
    
    # --- 定义表结构 ---
    tables = {
        "api_logs": '''CREATE TABLE IF NOT EXISTS api_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        action_type TEXT,
                        detail TEXT,
                        status TEXT,
                        api_response TEXT,
                        duration_ms INTEGER DEFAULT 0
                    )''',
        "playlists": '''CREATE TABLE IF NOT EXISTS playlists (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE,
                        created_at TEXT
                    )''',
        "playlist_songs": '''CREATE TABLE IF NOT EXISTS playlist_songs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            playlist_id INTEGER,
                            name TEXT,
                            url TEXT,
                            added_at TEXT,
                            FOREIGN KEY(playlist_id) REFERENCES playlists(id)
                        )'''
    }

    # --- 创建或修复 ---
    for table_name, create_sql in tables.items():
        try:
            c.execute(create_sql)
            # 检查字段是否存在，不存在则添加
            c.execute(f"PRAGMA table_info({table_name})")
            existing_columns = [row['name'] for row in c.fetchall()]
            
            if table_name == "api_logs" and "duration_ms" not in existing_columns:
                c.execute("ALTER TABLE api_logs ADD COLUMN duration_ms INTEGER DEFAULT 0")
            
            if table_name == "playlist_songs" and "url" not in existing_columns:
                c.execute("ALTER TABLE playlist_songs ADD COLUMN url TEXT")
                
        except Exception as e:
            print(f"⚠️ 表 {table_name} 检查警告: {e}")

    conn.commit()

def init_db():
    try:
        conn = get_db_connection()
        check_and_fix_schema(conn)
        conn.close()
    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")

# === 装饰器：自动修复与重试 ===
def safe_db_execute(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "no such table" in str(e) or "no such column" in str(e):
                print(f"⚠️ 数据库结构异常 ({e})，正在自动修复...")
                init_db()
                try:
                    return func(*args, **kwargs)
                except Exception:
                    return False
            return False
        except Exception:
            return False
    return wrapper

# === 日志功能 ===
@safe_db_execute
def insert_log(action_type, detail, status, api_response="", duration_ms=0):
    conn = get_db_connection()
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resp_str = str(api_response)[:500]

    c.execute(
        "INSERT INTO api_logs (timestamp, action_type, detail, status, api_response, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
        (timestamp, action_type, detail, status, resp_str, duration_ms))
    conn.commit()
    conn.close()

    if status not in ["成功", "自动忽略"]:
        print(f"[{timestamp}] {action_type}: {detail} -> {status}")
    return True

@safe_db_execute
def fetch_logs(limit=30):
    conn = get_db_connection()
    c = conn.cursor()
    # 过滤媒体控制日志
    c.execute("SELECT * FROM api_logs WHERE action_type != '媒体控制' ORDER BY id DESC LIMIT ?", (limit,))
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
            "duration": row['duration_ms'] if 'duration_ms' in row.keys() else 0,
            "response": row['api_response']
        })
    return data

@safe_db_execute
def clear_all_logs():
    conn = get_db_connection()
    conn.execute("DELETE FROM api_logs")
    conn.commit()
    conn.close()
    return True

@safe_db_execute
def get_source_stats():
    """
    统计各源的成功播放次数
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    # 查找所有成功的播放记录，无论是单曲搜索("获取链接")还是歌单自动播放("歌单播放")
    c.execute("SELECT detail FROM api_logs WHERE (action_type='获取链接' OR action_type='歌单播放') AND status='成功'")
    
    rows = c.fetchall()
    conn.close()

    stats = {}
    total = 0
    for row in rows:
        total += 1
        # 提取 "歌名 (源:qqmp3)" 中的源名称
        match = re.search(r'\(源:(.*?)\)', row['detail'])
        if match:
            source_name = match.group(1)
            stats[source_name] = stats.get(source_name, 0) + 1
        else:
            stats['unknown'] = stats.get('unknown', 0) + 1
    return {"total": total, "details": stats}

# === 歌单管理 ===
@safe_db_execute
def create_playlist(name):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)", (name, ts))
        conn.commit()
        conn.close()
        return True, "创建成功"
    except sqlite3.IntegrityError:
        return False, "歌单名已存在"

@safe_db_execute
def rename_playlist(old_name, new_name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE playlists SET name = ? WHERE name = ?", (new_name, old_name))
    conn.commit()
    conn.close()
    return True, "重命名成功"

@safe_db_execute
def delete_playlist(name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM playlists WHERE name=?", (name,))
    res = c.fetchone()
    if res:
        pid = res['id']
        c.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (pid,))
        c.execute("DELETE FROM playlists WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        return True, "删除成功"
    conn.close()
    return False, "歌单不存在"

@safe_db_execute
def add_song_to_playlist(playlist_name, song_name, url=""):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM playlists WHERE name=?", (playlist_name,))
    res = c.fetchone()
    if not res: 
        conn.close()
        return False, "歌单不存在"
    
    pid = res['id']
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # url 允许为空
    c.execute("INSERT INTO playlist_songs (playlist_id, name, url, added_at) VALUES (?, ?, ?, ?)", 
              (pid, song_name, url, ts))
    conn.commit()
    conn.close()
    return True, "添加成功"

@safe_db_execute
def remove_song_from_playlist(song_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM playlist_songs WHERE id=?", (song_id,))
    conn.commit()
    conn.close()
    return True, "移除成功"

@safe_db_execute
def rename_song_in_playlist(song_id, new_name):
    """重命名歌单中的歌曲"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE playlist_songs SET name = ? WHERE id = ?", (new_name, song_id))
    conn.commit()
    conn.close()
    return True, "重命名成功"

@safe_db_execute
def get_all_playlists():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM playlists ORDER BY created_at DESC")
    rows = c.fetchall()
    
    playlists = []
    for row in rows:
        # 获取歌曲数量
        c.execute("SELECT COUNT(*) as count FROM playlist_songs WHERE playlist_id=?", (row['id'],))
        res = c.fetchone()
        count = res['count'] if res else 0
        playlists.append({"id": row['id'], "name": row['name'], "count": count})
    
    conn.close()
    return playlists

@safe_db_execute
def get_playlist_songs(playlist_name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM playlists WHERE name=?", (playlist_name,))
    res = c.fetchone()
    if not res: 
        conn.close()
        return []
    
    c.execute("SELECT * FROM playlist_songs WHERE playlist_id=? ORDER BY added_at ASC", (res['id'],))
    songs = []
    for row in c.fetchall():
        songs.append({"id": row['id'], "name": row['name'], "url": row['url']})
    conn.close()
    return songs

# 启动自检
init_db()

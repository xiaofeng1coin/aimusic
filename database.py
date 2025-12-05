import sqlite3
import os
import sys
import re
import logging
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
    
    # --- 1. 定义所有需要的表结构 ---
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

    # --- 2. 创建或修复表 ---
    for table_name, create_sql in tables.items():
        try:
            # 尝试创建表（如果不存在）
            c.execute(create_sql)
            
            # --- 3. 字段补全 (简单的 Migration 逻辑) ---
            # 获取当前表的所有字段
            c.execute(f"PRAGMA table_info({table_name})")
            existing_columns = [row['name'] for row in c.fetchall()]
            
            # 针对 api_logs 表检查 duration_ms (防止旧版数据库报错)
            if table_name == "api_logs" and "duration_ms" not in existing_columns:
                print(f"🔧 正在修复表 {table_name}: 添加 duration_ms 字段")
                c.execute("ALTER TABLE api_logs ADD COLUMN duration_ms INTEGER DEFAULT 0")
                
            # 针对 playlist_songs 表的检查 (示例)
            if table_name == "playlist_songs" and "url" not in existing_columns:
                print(f"🔧 正在修复表 {table_name}: 添加 url 字段")
                c.execute("ALTER TABLE playlist_songs ADD COLUMN url TEXT")
                
        except Exception as e:
            print(f"⚠️ 初始化表 {table_name} 时遇到非致命错误: {e}")

    conn.commit()

def init_db():
    """初始化入口"""
    try:
        conn = get_db_connection()
        check_and_fix_schema(conn)
        conn.close()
        # print("✅ 数据库结构检查完毕") # 减少日志干扰，注释掉
    except Exception as e:
        print(f"❌ 数据库初始化严重失败: {e}")

# === 装饰器：自动修复与重试 ===
# 这是实现“不需要删除源文件”的核心
def safe_db_execute(func):
    """
    装饰器：当数据库操作遇到 'no such table' 错误时，
    自动执行 init_db() 进行修复，然后重试一次。
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            # 捕获表缺失或列缺失错误
            if "no such table" in error_msg or "no such column" in error_msg:
                print(f"⚠️ 检测到数据库结构缺失 ({e})，正在尝试自动修复...")
                init_db() # 执行修复
                try:
                    print("🔄 修复完成，正在重试操作...")
                    return func(*args, **kwargs) # 重试
                except Exception as retry_e:
                    print(f"❌ 自动修复后重试依然失败: {retry_e}")
                    return False # 或者根据原函数返回空列表等
            else:
                print(f"❌ 数据库操作未知错误: {e}")
                raise e # 其他错误直接抛出
        except Exception as e:
            print(f"❌ 系统错误: {e}")
            return False # 通用失败返回
    return wrapper

# === 日志相关功能 ===

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
    # 过滤掉 '媒体控制' 类型的日志
    c.execute(
        "SELECT * FROM api_logs WHERE action_type != '媒体控制' ORDER BY id DESC LIMIT ?",
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
            "duration": row['duration_ms'] if 'duration_ms' in row.keys() else 0, # 兼容旧数据
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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT detail FROM api_logs WHERE action_type='获取链接' AND status='成功'")
    rows = c.fetchall()
    conn.close()

    stats = {}
    total = 0
    for row in rows:
        total += 1
        match = re.search(r'\(源:(.*?)\)', row['detail'])
        if match:
            source_name = match.group(1)
            stats[source_name] = stats.get(source_name, 0) + 1
        else:
            stats['unknown'] = stats.get('unknown', 0) + 1
    return {"total": total, "details": stats}

# === 歌单管理功能 (全部加上 safe_db_execute) ===

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
def add_song_to_playlist(playlist_name, song_name, url):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM playlists WHERE name=?", (playlist_name,))
    res = c.fetchone()
    if not res: 
        conn.close()
        return False, "歌单不存在"
    
    pid = res['id']
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
def get_all_playlists():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM playlists ORDER BY created_at DESC")
    playlists = []
    rows = c.fetchall()
    
    # 这里需要单独处理，因为在循环里不能共用cursor，建议分步查询
    for row in rows:
        # 获取歌曲数量
        # 这里创建一个新的临时连接或者 cursor 比较安全，但为了简单，直接 execute
        # 注意：sqlite fetchall 后 cursor 可以复用
        c.execute("SELECT COUNT(*) as count FROM playlist_songs WHERE playlist_id=?", (row['id'],))
        count_res = c.fetchone()
        count = count_res['count'] if count_res else 0
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

# 程序启动时强制检查一次
init_db()

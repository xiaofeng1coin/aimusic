import time
import os
import threading
import logging
import json
import io
import requests
from datetime import datetime
from flask import Flask, render_template, jsonify, request

# 引入 mutagen 用于获取时长
from mutagen import File
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

# ... (日志配置不变) ...
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.propagate = False

import database
from music_apis import search_and_get_url

# ... (配置区域不变) ...
HA_URL = os.getenv("HA_URL", "http://192.168.1.X:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
PLAYER_ENTITY_ID = os.getenv("PLAYER_ENTITY_ID", "")
CONVERSATION_ENTITY_ID = os.getenv("CONVERSATION_ENTITY_ID", "")
MUSIC_SOURCE = os.getenv("MUSIC_SOURCE", "all")

app = Flask(__name__)

# === 系统状态 (新增播放相关状态) ===
system_status = {
    "thread_active": False,
    "last_heartbeat": None,
    "total_calls": 0,
    
    # 歌单播放状态
    "playlist_mode": False,
    "current_playlist_name": "",
    "queue": [], # [{name, url}, ...]
    "current_index": -1,
    "playing_start_time": 0,
    "current_duration": 0
}

# === 辅助函数：获取网络音频时长 (需求5) ===
def get_audio_duration(url):
    """
    通过下载文件头获取时长，支持 mp3, m4a 等
    """
    try:
        print(f"⏳ 正在计算时长: {url[:30]}...")
        headers = {"User-Agent": "Mozilla/5.0"}
        # 尝试流式下载前 128KB 数据用于分析头部
        resp = requests.get(url, headers=headers, stream=True, timeout=5)
        
        # 读取一部分数据到内存
        data = io.BytesIO()
        for chunk in resp.iter_content(chunk_size=4096):
            data.write(chunk)
            if data.tell() > 128 * 1024: # 读取 128KB
                break
        data.seek(0)
        
        # 尝试解析
        audio = None
        try:
            audio = MP3(data)
        except:
            try:
                data.seek(0)
                audio = MP4(data)
            except:
                try:
                    data.seek(0)
                    audio = File(data)
                except:
                    pass
        
        if audio and audio.info and audio.info.length:
            duration = int(audio.info.length)
            print(f"✅ 获取时长成功: {duration}秒")
            return duration
    except Exception as e:
        print(f"⚠️ 获取时长失败: {e}")
    
    return 0 # 失败返回0

# ... (record_action, call_ha_service, get_ha_state 保持不变) ...
def record_action(action_type, detail, status, api_response="", duration=0):
    system_status["total_calls"] += 1
    database.insert_log(action_type, detail, status, str(api_response)[:500], duration)

def call_ha_service(domain, service, service_data):
    url = f"{HA_URL}/api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        requests.post(url, headers=headers, json=service_data, timeout=5)
        return True
    except:
        return False

def get_ha_state(entity_id):
    url = f"{HA_URL}/api/states/{entity_id}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get('state')
    except:
        pass
    return None

# === 核心：播放逻辑 ===

def play_url_on_ha(url, song_name):
    """单纯调用HA播放"""
    success = call_ha_service("media_player", "play_media", {
        "entity_id": PLAYER_ENTITY_ID,
        "media_content_id": url,
        "media_content_type": "music"
    })
    return success

def start_playlist_playback(playlist_name):
    """(需求4) 启动歌单播放模式"""
    songs = database.get_playlist_songs(playlist_name)
    if not songs:
        return False, "歌单为空或不存在"
    
    system_status["playlist_mode"] = True
    system_status["current_playlist_name"] = playlist_name
    system_status["queue"] = songs
    system_status["current_index"] = 0
    
    # 播放第一首
    play_current_queue_song()
    return True, f"开始播放歌单: {playlist_name}"

def play_current_queue_song():
    """播放队列中当前索引的歌曲 (需求6 - 计时开始)"""
    if not system_status["queue"]: return
    
    idx = system_status["current_index"]
    if idx >= len(system_status["queue"]):
        system_status["playlist_mode"] = False # 播放结束
        print("🏁 歌单播放结束")
        return

    song = system_status["queue"][idx]
    print(f"▶️ [歌单] 播放第 {idx+1} 首: {song['name']}")
    
    # 1. 获取时长 (需求5)
    duration = get_audio_duration(song['url'])
    # 如果获取失败，默认给一个 3分30秒，或者不自动切歌(视策略而定)，这里给默认值防止死循环
    if duration == 0: duration = 210 
    
    system_status["current_duration"] = duration
    
    # 2. 调用 HA
    if play_url_on_ha(song['url'], song['name']):
        # 3. 开始计时
        system_status["playing_start_time"] = time.time()
        record_action("歌单播放", f"{song['name']} (歌单:{system_status['current_playlist_name']})", "成功", song['url'], 0)
    else:
        record_action("歌单播放", f"{song['name']}", "HA调用失败", "", 0)
        # 失败则跳下一首
        system_status["current_index"] += 1
        play_current_queue_song()

def process_search_and_play(input_text, specified_sources="all"):
    """
    主处理逻辑 (需求4：优先匹配歌单)
    """
    # 1. 尝试匹配歌单 (完全匹配)
    # 检查是否存在该名称的歌单
    all_playlists = database.get_all_playlists()
    for pl in all_playlists:
        if pl['name'] == input_text:
            print(f"🎯 命中本地歌单: {input_text}")
            success, msg = start_playlist_playback(input_text)
            record_action("语音指令", f"播放歌单: {input_text}", "成功" if success else "失败", msg, 0)
            return {"success": success, "msg": msg}

    # 2. 如果不是歌单，走原来的搜索逻辑
    system_status["playlist_mode"] = False # 退出歌单模式
    
    t_start = time.time()
    current_source = specified_sources if specified_sources else MUSIC_SOURCE
    print(f"\n====== [开始搜索] {input_text} (源: {current_source}) ======")

    success, msg, song_info, play_url, error_logs = search_and_get_url(input_text, source=current_source)

    if error_logs:
        for err in error_logs:
            record_action("API异常", f"{input_text} (源:{err['source']})", "自动忽略", err['msg'], err['duration'])

    if not success:
        record_action("任务失败", input_text, "全部失败", msg, int((time.time() - t_start) * 1000))
        return {"success": False, "msg": msg}

    # 播放成功
    real_source = song_info.get('source_label', 'unknown')
    total_duration = int((time.time() - t_start) * 1000)
    record_action("获取链接", f"{song_info['name']} (源:{real_source})", "成功", play_url, total_duration)

    ha_success = play_url_on_ha(play_url, song_info['name'])

    if ha_success:
        return {"success": True, "msg": f"播放: {song_info['name']}", "data": song_info}
    else:
        return {"success": False, "msg": "HA调用失败"}

# === 后台监控线程 (需求6：自动切歌) ===
def background_monitor():
    system_status["thread_active"] = True
    last_text = ""
    
    while True:
        system_status["last_heartbeat"] = datetime.now().strftime("%H:%M:%S")
        
        # 1. 语音监控
        try:
            if CONVERSATION_ENTITY_ID:
                current_text = get_ha_state(CONVERSATION_ENTITY_ID)
                if current_text and current_text != last_text and current_text != "unavailable":
                    last_text = current_text
                    trigger_word = "帮我搜"
                    if current_text.startswith(trigger_word):
                        keyword = current_text.replace(trigger_word, "").strip()
                        # 触发搜索或歌单
                        process_search_and_play(keyword, "all")
        except Exception as e:
            print(f"Monitor Error: {e}")

        # 2. 歌单自动切歌逻辑 (需求6)
        if system_status["playlist_mode"] and system_status["playing_start_time"] > 0:
            elapsed = time.time() - system_status["playing_start_time"]
            # 缓冲 2 秒，防止刚放完就切
            if elapsed > (system_status["current_duration"] + 2):
                print(f"⏰ 单曲时间到 ({int(elapsed)}s)，切下一首")
                system_status["current_index"] += 1
                play_current_queue_song()

        time.sleep(2)

# ================= 路由 =================
@app.route('/')
def index(): return render_template('dashboard.html')

@app.route('/api/stats')
def get_stats():
    db_stats = database.get_source_stats()
    return jsonify({
        "thread_active": system_status["thread_active"],
        "last_heartbeat": system_status["last_heartbeat"],
        "total_ops": system_status["total_calls"],
        "playlist_mode": system_status["playlist_mode"],
        "current_playlist": system_status["current_playlist_name"] if system_status["playlist_mode"] else None,
        "success_count": db_stats['total'],
        "source_details": db_stats['details']
    })

@app.route('/api/logs')
def get_logs(): 
    # database.fetch_logs 已经过滤了媒体控制按钮的日志
    return jsonify(database.fetch_logs(limit=30))

@app.route('/api/manual_exec', methods=['POST'])
def manual_exec():
    req_data = request.json
    # 1. 历史重播 / 手动指定URL
    if 'url' in req_data and req_data['url']:
        play_url = req_data['url']
        song_name = req_data.get('song_name', '未知歌曲')
        ha_success = play_url_on_ha(play_url, song_name)
        if ha_success:
            # 手动点播打断歌单模式
            system_status["playlist_mode"] = False
            record_action("历史重播", f"{song_name}", "成功", play_url, 0)
            return jsonify({"success": True, "msg": f"正在重播: {song_name}"})
        return jsonify({"success": False, "msg": "HA调用失败"})

    # 2. 搜索 / 播放歌单
    song_name = req_data.get('song_name')
    sources = req_data.get('sources', 'all')
    if not song_name: return jsonify({"success": False})
    
    return jsonify(process_search_and_play(song_name, sources))

@app.route('/api/clear_logs', methods=['POST'])
def clear_logs(): return jsonify({"success": database.clear_all_logs()})

# === 媒体控制 (需求1 & 2：日志已在 database.py 过滤) ===
@app.route('/api/control/<action>', methods=['POST'])
def media_control(action):
    # (需求1) 前端只留了特定按钮，但后端API兼容
    service = ""
    data = {"entity_id": PLAYER_ENTITY_ID}
    
    if action == "play_pause":
        service = "media_play_pause"
    elif action == "next":
        # 如果在歌单模式，手动下一首
        if system_status["playlist_mode"]:
            system_status["current_index"] += 1
            play_current_queue_song()
            return jsonify({"success": True, "msg": "歌单下一首"})
        service = "media_next_track"
    elif action == "previous":
         # 如果在歌单模式，手动上一首
        if system_status["playlist_mode"]:
            system_status["current_index"] = max(0, system_status["current_index"] - 1)
            play_current_queue_song()
            return jsonify({"success": True, "msg": "歌单上一首"})
        service = "media_previous_track"
    else:
        return jsonify({"success": False, "msg": "不支持的指令"})

    success = call_ha_service("media_player", service, data)
    if success:
        # 记录日志，但在前端会被过滤不显示 (需求2)
        record_action("媒体控制", f"执行: {action}", "成功", "", 0)
        return jsonify({"success": True, "msg": "OK"})
    return jsonify({"success": False, "msg": "Fail"})

# === 歌单管理 API (需求3) ===
@app.route('/api/playlists', methods=['GET'])
def list_playlists():
    return jsonify(database.get_all_playlists())

@app.route('/api/playlists', methods=['POST'])
def create_playlist():
    name = request.json.get('name')
    if not name: return jsonify({"success": False, "msg": "名称为空"})
    success, msg = database.create_playlist(name)
    return jsonify({"success": success, "msg": msg})

@app.route('/api/playlists/<name>', methods=['DELETE'])
def delete_playlist(name):
    success, msg = database.delete_playlist(name)
    return jsonify({"success": success, "msg": msg})

@app.route('/api/playlists/<name>/rename', methods=['POST'])
def rename_playlist(name):
    new_name = request.json.get('new_name')
    success, msg = database.rename_playlist(name, new_name)
    return jsonify({"success": success, "msg": msg})

@app.route('/api/playlists/<name>/songs', methods=['GET'])
def get_playlist_songs(name):
    return jsonify(database.get_playlist_songs(name))

@app.route('/api/playlists/<name>/songs', methods=['POST'])
def add_song_to_playlist_route(name):
    data = request.json
    song_name = data.get('name')
    url = data.get('url')
    success, msg = database.add_song_to_playlist(name, song_name, url)
    return jsonify({"success": success, "msg": msg})

@app.route('/api/songs/<int:song_id>', methods=['DELETE'])
def delete_song(song_id):
    success, msg = database.remove_song_from_playlist(song_id)
    return jsonify({"success": success, "msg": msg})

if __name__ == "__main__":
    try:
        database.init_db()
    except:
        pass
    monitor = threading.Thread(target=background_monitor, daemon=True)
    monitor.start()
    print(f"🚀 音乐服务器启动 | 模式: {MUSIC_SOURCE}")
    app.run(host='0.0.0.0', port=5000, debug=False)

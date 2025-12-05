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

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.propagate = False

import database
from music_apis import search_and_get_url

# ... (配置区域) ...
HA_URL = os.getenv("HA_URL", "http://192.168.1.X:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
PLAYER_ENTITY_ID = os.getenv("PLAYER_ENTITY_ID", "")
CONVERSATION_ENTITY_ID = os.getenv("CONVERSATION_ENTITY_ID", "")
MUSIC_SOURCE = os.getenv("MUSIC_SOURCE", "all")

app = Flask(__name__)

# === 系统状态 ===
system_status = {
    "thread_active": False,
    "last_heartbeat": None,
    "total_calls": 0,
    # 歌单播放状态
    "playlist_mode": False,
    "current_playlist_name": "",
    "queue": [], 
    "current_index": -1,
    "playing_start_time": 0,
    "current_duration": 0,
    
    # 本地记录当前播放信息，用于前端显示
    "current_track_title": "等待播放", 
    "current_track_source": ""
}

# === 辅助功能 ===
def get_audio_duration(url):
    """获取网络音频时长"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, stream=True, timeout=5)
        data = io.BytesIO()
        for chunk in resp.iter_content(chunk_size=4096):
            data.write(chunk)
            if data.tell() > 128 * 1024: break
        data.seek(0)
        
        audio = None
        try: audio = MP3(data)
        except:
            try: 
                data.seek(0)
                audio = MP4(data)
            except: pass
        
        if audio and audio.info and audio.info.length:
            return int(audio.info.length)
    except:
        pass
    return 0

def record_action(action_type, detail, status, api_response="", duration=0):
    system_status["total_calls"] += 1
    try:
        database.insert_log(action_type, detail, status, str(api_response)[:500], duration)
    except:
        pass

def call_ha_service(domain, service, service_data):
    url = f"{HA_URL}/api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        requests.post(url, headers=headers, json=service_data, timeout=5)
        return True
    except:
        return False

def get_ha_player_info():
    """获取播放器的状态"""
    if not PLAYER_ENTITY_ID:
        return "unknown", {}
        
    url = f"{HA_URL}/api/states/{PLAYER_ENTITY_ID}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=2)
        if response.status_code == 200:
            data = response.json()
            state = data.get('state', 'unknown')
            attrs = data.get('attributes', {})
            return state, attrs
    except:
        pass
    return "unknown", {}

def get_ha_state(entity_id):
    """获取实体状态"""
    url = f"{HA_URL}/api/states/{entity_id}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get('state')
    except:
        pass
    return None

def play_url_on_ha(url, song_name):
    return call_ha_service("media_player", "play_media", {
        "entity_id": PLAYER_ENTITY_ID,
        "media_content_id": url,
        "media_content_type": "music",
        "extra": {
            "title": song_name,
            "thumb": "https://p1.music.126.net/tGHU62DTszbFQ37W9qPH5A==/109951165607028179.jpg"
        }
    })

# === 歌单播放逻辑 ===
def start_playlist_playback(playlist_name):
    songs = database.get_playlist_songs(playlist_name)
    if not songs:
        return False, "歌单为空"
    
    system_status["playlist_mode"] = True
    system_status["current_playlist_name"] = playlist_name
    system_status["queue"] = songs
    system_status["current_index"] = 0
    
    play_current_queue_song()
    return True, f"开始播放歌单: {playlist_name}"

def play_current_queue_song():
    if not system_status["queue"]: return
    
    # === 修改核心：循环逻辑 ===
    # 如果当前索引超出了队列长度，说明刚播完最后一首，现在循环回第一首 (Index 0)
    if system_status["current_index"] >= len(system_status["queue"]):
        print("🔄 [循环模式] 歌单列表播放结束，重置至第一首")
        system_status["current_index"] = 0

    idx = system_status["current_index"]
    
    song_data = system_status["queue"][idx]
    song_name = song_data['name']
    print(f"\n====== [歌单播放] 第 {idx+1} 首: {song_name} ======")

    success, msg, song_info, play_url, error_logs = search_and_get_url(song_name, source="all")
    
    if not success:
        print(f"❌ [歌单] 搜索失败，跳过")
        record_action("歌单跳过", song_name, "失败", msg, 0)
        system_status["current_index"] += 1
        play_current_queue_song() # 递归调用，会自动处理循环
        return

    duration = get_audio_duration(play_url)
    if duration == 0: duration = 210 
    
    real_source = song_info.get('source_label', 'unknown')
    
    # === 日志打印区域 ===
    print(f"🎉 [歌单选中] 源: {real_source}")
    print(f"🔗 [播放地址] {play_url}")
    
    system_status["current_duration"] = duration
    
    if play_url_on_ha(play_url, song_info['name']):
        system_status["playing_start_time"] = time.time()
        
        # 更新本地状态
        system_status["current_track_title"] = song_info['name']
        system_status["current_track_source"] = real_source
        
        record_action("歌单播放", f"{song_info['name']} (源:{real_source})", "成功", play_url, 0)
    else:
        # 播放失败，尝试下一首
        system_status["current_index"] += 1
        play_current_queue_song()

# === 核心搜索逻辑 ===
def process_search_and_play(input_text, specified_sources="all"):
    # 1. 检查是否是歌单
    all_playlists = database.get_all_playlists()
    for pl in all_playlists:
        if pl['name'] == input_text:
            print(f"🎯 命中本地歌单: {input_text}")
            start_playlist_playback(input_text)
            return {"success": True, "msg": f"开始播放歌单: {input_text}"}

    # 2. 单曲搜索模式
    system_status["playlist_mode"] = False
    t_start = time.time()
    
    success, msg, song_info, play_url, error_logs = search_and_get_url(input_text, source=specified_sources)

    if error_logs:
        for err in error_logs:
            record_action("API异常", f"{input_text} (源:{err['source']})", "自动忽略", err['msg'], err['duration'])

    if not success:
        record_action("任务失败", input_text, "全部失败", msg, int((time.time() - t_start) * 1000))
        return {"success": False, "msg": msg}

    real_source = song_info.get('source_label', 'unknown')
    total_duration = int((time.time() - t_start) * 1000)
    
    # 单曲模式下的日志
    print(f"🎉 [单曲选中] 源: {real_source}")
    print(f"🔗 [播放地址] {play_url}")

    record_action("获取链接", f"{song_info['name']} (源:{real_source})", "成功", play_url, total_duration)

    if play_url_on_ha(play_url, song_info['name']):
        # 更新本地状态
        system_status["current_track_title"] = song_info['name']
        system_status["current_track_source"] = real_source
        
        return {"success": True, "msg": f"播放: {song_info['name']}", "data": song_info}
    else:
        return {"success": False, "msg": "HA调用失败"}

# === 自动切歌监控 (核心修复：状态同步+防误触) ===
def background_monitor():
    system_status["thread_active"] = True
    
    # === 启动时忽略旧指令 ===
    last_text = ""
    if CONVERSATION_ENTITY_ID:
        print("🔄 正在初始化状态，同步 HA 现有指令...")
        initial_state = get_ha_state(CONVERSATION_ENTITY_ID)
        if initial_state:
            last_text = initial_state
            print(f"✅ 状态已同步 (忽略旧指令): {last_text}")
        else:
            print("⚠️ 未能获取初始状态或状态为空")

    while True:
        system_status["last_heartbeat"] = datetime.now().strftime("%H:%M:%S")
        try:
            # 1. 语音控制监控
            if CONVERSATION_ENTITY_ID:
                current_text = get_ha_state(CONVERSATION_ENTITY_ID)
                # 只有当 current_text 不为空，且真的发生了变化时，才执行
                if current_text and current_text != last_text and current_text != "unavailable":
                    last_text = current_text
                    if current_text.startswith("帮我搜"):
                        keyword = current_text.replace("帮我搜", "").strip()
                        process_search_and_play(keyword, "all")
            
            # 2. 歌单自动切歌监控
            if system_status["playlist_mode"]:
                # 获取播放器真实状态
                ha_state, ha_attrs = get_ha_player_info()
                
                # 关键修复：只有当状态为 'playing' 时才进行计时和切歌判断
                if ha_state == 'playing':
                    should_switch = False
                    
                    # [优先策略] 使用 HA 返回的媒体进度 (Media Position)
                    if 'media_position' in ha_attrs and 'media_duration' in ha_attrs:
                        try:
                            current_pos = float(ha_attrs['media_position'])
                            total_dur = float(ha_attrs['media_duration'])
                            # 如果总时长有效且剩余时间小于 5 秒
                            if total_dur > 0 and (total_dur - current_pos) <= 5:
                                print(f"⏰ [进度同步] 歌曲剩余 {total_dur - current_pos:.1f}s，准备切歌...")
                                should_switch = True
                        except (ValueError, TypeError):
                            pass 
                    
                    # [降级策略] 本地计时器 (只有在 HA 处于 playing 状态时才累计)
                    if not should_switch and system_status["playing_start_time"] > 0:
                        elapsed = time.time() - system_status["playing_start_time"]
                        duration = system_status["current_duration"]
                        switch_threshold = duration - 5 if duration > 10 else duration
                        
                        if elapsed > switch_threshold:
                            print(f"⏰ [本地计时] 已播 {elapsed:.1f}s / 总 {duration}s，触发切歌")
                            should_switch = True
                    
                    # 执行切歌
                    if should_switch:
                        system_status["current_index"] += 1
                        system_status["playing_start_time"] = 0 
                        # 这里的 play_current_queue_song 会处理索引越界并循环
                        play_current_queue_song()
                    
        except Exception as e:
            print(f"Error in monitor: {e}")
        
        time.sleep(2)

# === 路由 ===
@app.route('/')
def index(): return render_template('dashboard.html')

@app.route('/api/stats')
def get_stats():
    db_stats = database.get_source_stats()
    
    # 1. 获取 HA 真实状态
    ha_state, ha_attrs = get_ha_player_info()
    
    # 2. 决定显示什么
    display_status = "待机 / 准备就绪"
    is_playing_anim = False
    
    # 使用本地记录的歌名
    local_song_name = system_status.get("current_track_title", "未知曲目")
    display_text = local_song_name

    # 截断太长的歌名
    if len(display_text) > 22: display_text = display_text[:20] + "..."
    
    # 状态判断逻辑
    if ha_state == 'playing':
        display_status = f"🎵 正在播放: {display_text}"
        is_playing_anim = True
        
        if system_status["playlist_mode"]:
             display_status = f"💿 {system_status['current_playlist_name']}: {display_text}"

    elif ha_state == 'paused':
        display_status = f"⏸️ 已暂停: {display_text}"
        
    elif ha_state == 'idle' or ha_state == 'off':
        if system_status["playlist_mode"]:
             display_status = "💿 歌单准备中..."

    return jsonify({
        "thread_active": system_status["thread_active"],
        "last_heartbeat": system_status["last_heartbeat"],
        "total_ops": system_status["total_calls"],
        "playlist_mode": system_status["playlist_mode"],
        "current_playlist": system_status["current_playlist_name"] if system_status["playlist_mode"] else None,
        "success_count": db_stats['total'],
        "source_details": db_stats['details'],
        "smart_status": display_status,
        "is_playing": is_playing_anim
    })

@app.route('/api/logs')
def get_logs(): return jsonify(database.fetch_logs(limit=30))

@app.route('/api/manual_exec', methods=['POST'])
def manual_exec():
    req = request.json
    if 'url' in req and req['url']:
        song_name = req.get('song_name', '未知/重播')
        system_status["playlist_mode"] = False
        
        if play_url_on_ha(req['url'], song_name):
            system_status["current_track_title"] = song_name
            system_status["current_track_source"] = "Manual"
            return jsonify({"success": True, "msg": "推送成功"})
        return jsonify({"success": False, "msg": "HA失败"})
    
    return jsonify(process_search_and_play(req.get('song_name'), req.get('sources', 'all')))

@app.route('/api/clear_logs', methods=['POST'])
def clear_logs(): return jsonify({"success": database.clear_all_logs()})

@app.route('/api/control/<action>', methods=['POST'])
def media_control(action):
    if action == "next" and system_status["playlist_mode"]:
        system_status["current_index"] += 1
        # 这里的 play_current_queue_song 也会处理手动点击下一首时的循环
        play_current_queue_song()
        return jsonify({"success": True, "msg": "下一首"})
    
    if action == "previous" and system_status["playlist_mode"]:
        # 上一首如果已经是第一首，可以循环到最后一首，或者停在第一首，这里保持原样（停在第一首）
        # 如果需要循环到最后一首，修改为:
        # system_status["current_index"] = system_status["current_index"] - 1
        # if system_status["current_index"] < 0: system_status["current_index"] = len(system_status["queue"]) - 1
        system_status["current_index"] = max(0, system_status["current_index"] - 1)
        play_current_queue_song()
        return jsonify({"success": True, "msg": "上一首"})

    service_map = {
        "play_pause": "media_play_pause",
        "next": "media_next_track",
        "previous": "media_previous_track"
    }
    if action in service_map:
        if call_ha_service("media_player", service_map[action], {"entity_id": PLAYER_ENTITY_ID}):
            return jsonify({"success": True, "msg": "OK"})
    
    return jsonify({"success": False, "msg": "失败"})

# 歌单 API 路由
@app.route('/api/playlists', methods=['GET'])
def list_pl(): return jsonify(database.get_all_playlists())
@app.route('/api/playlists', methods=['POST'])
def create_pl(): return jsonify({"success": database.create_playlist(request.json.get('name'))[0]})
@app.route('/api/playlists/<name>', methods=['DELETE'])
def del_pl(name): return jsonify({"success": database.delete_playlist(name)[0]})
@app.route('/api/playlists/<name>/rename', methods=['POST'])
def rename_pl(name): return jsonify({"success": database.rename_playlist(name, request.json.get('new_name'))[0]})
@app.route('/api/playlists/<name>/songs', methods=['GET'])
def get_songs(name): return jsonify(database.get_playlist_songs(name))
@app.route('/api/playlists/<name>/songs', methods=['POST'])
def add_song(name): return jsonify({"success": database.add_song_to_playlist(name, request.json.get('name'), "")[0]})
@app.route('/api/songs/<int:id>', methods=['DELETE'])
def del_song(id): return jsonify({"success": database.remove_song_from_playlist(id)[0]})
@app.route('/api/songs/<int:id>/rename', methods=['POST'])
def rename_song(id):
    return jsonify({"success": database.rename_song_in_playlist(id, request.json.get('new_name'))[0]})

if __name__ == "__main__":
    try: database.init_db()
    except: pass
    threading.Thread(target=background_monitor, daemon=True).start()
    print(f"🚀 音乐服务器启动 | 源: {MUSIC_SOURCE}")
    app.run(host='0.0.0.0', port=5000, debug=False)

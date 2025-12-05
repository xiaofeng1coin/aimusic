import requests
import time
import os
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request

# ==========================================
# 🔴 强行屏蔽刷屏日志（必须放在最前面）🔴
# ==========================================
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
log.propagate = False
# ==========================================

# 引入数据库模块
import database

# ================= 配置区域 =================
HA_URL = os.getenv("HA_URL", "http://192.168.1.X:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
PLAYER_ENTITY_ID = os.getenv("PLAYER_ENTITY_ID", "")
CONVERSATION_ENTITY_ID = os.getenv("CONVERSATION_ENTITY_ID", "")
MUSIC_SOURCE = os.getenv("MUSIC_SOURCE", "netease")

app = Flask(__name__)

# 全局内存统计
system_status = {
    "thread_active": False,
    "last_heartbeat": None,
    "total_calls": 0,  # 总调用次数 (包括搜索、播放等所有操作)
    "success_calls": 0  # 成功播放次数 (仅指成功获取到URL的次数)
}


# ================= 辅助函数 =================
def record_action(action_type, detail, status, api_response="", start_time=None):
    """记录日志并更新内存统计"""
    duration = 0
    if start_time:
        duration = int((time.time() - start_time) * 1000)

    system_status["total_calls"] += 1

    # === 核心修改点：只统计“获取链接成功”的次数 ===
    # 只有当动作是"获取链接"且状态是"成功"时，成功次数才+1
    if action_type == "获取链接" and status == "成功":
        system_status["success_calls"] += 1

    database.insert_log(action_type, detail, status, api_response, duration)


# ================= 核心业务逻辑 =================
def call_ha_service(domain, service, service_data):
    url = f"{HA_URL}/api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=service_data, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def get_ha_state(entity_id):
    url = f"{HA_URL}/api/states/{entity_id}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get('state')
    except Exception:
        pass
    return None


def process_search_and_play(song_name, source="auto"):
    """封装搜索和播放逻辑"""
    t_start = time.time()

    # --- 步骤 1: 搜索 ---
    search_api = "https://music-api.gdstudio.xyz/api.php"
    params = {"types": "search", "count": 1, "source": MUSIC_SOURCE, "pages": 1, "name": song_name}

    try:
        res = requests.get(search_api, params=params, timeout=8).json()
        song_info = None
        if isinstance(res, list) and res:
            song_info = res[0]
        elif isinstance(res, dict) and 'list' in res and res['list']:
            song_info = res['list'][0]

        if not song_info:
            record_action("搜索歌曲", song_name, "无结果", str(res), t_start)
            return {"success": False, "msg": "未找到歌曲"}

        record_action("搜索歌曲", song_name, "成功", f"{song_info.get('name')} - {song_info.get('artist')}", t_start)

        # --- 步骤 2: 获取URL ---
        t_url_start = time.time()
        url_api = "https://music-api.gdstudio.xyz/api.php"
        url_params = {"types": "url", "source": MUSIC_SOURCE, "id": song_info['id'], "br": 320}
        res_url = requests.get(url_api, params=url_params, timeout=8).json()

        if res_url and 'url' in res_url:
            play_url = res_url['url']
            # 这里记录为 "获取链接" + "成功"，会触发 success_calls + 1
            record_action("获取链接", song_info['name'], "成功", play_url, t_url_start)

            # --- 步骤 3: 调用HA播放 ---
            success = call_ha_service("media_player", "play_media", {
                "entity_id": PLAYER_ENTITY_ID,
                "media_content_id": play_url,
                "media_content_type": "music"
            })
            if success:
                return {"success": True, "msg": f"正在播放: {song_info['name']}", "data": song_info}
            else:
                return {"success": False, "msg": "HA调用失败"}
        else:
            record_action("获取链接", song_info['name'], "失败", str(res_url), t_url_start)
            return {"success": False, "msg": "无法获取播放链接"}

    except Exception as e:
        record_action("系统异常", song_name, "报错", str(e), t_start)
        return {"success": False, "msg": str(e)}


# ================= 后台线程 =================
def background_monitor():
    system_status["thread_active"] = True
    database.insert_log("系统消息", "监控引擎", "启动", "后台服务已就绪")

    last_text = ""
    while True:
        system_status["last_heartbeat"] = datetime.now().strftime("%H:%M:%S")
        try:
            if CONVERSATION_ENTITY_ID:
                current_text = get_ha_state(CONVERSATION_ENTITY_ID)
                if current_text and current_text != last_text and current_text != "unavailable":
                    last_text = current_text
                    trigger_word = "帮我搜"
                    if current_text.startswith(trigger_word):
                        song_name = current_text.replace(trigger_word, "").strip()
                        database.insert_log("语音唤醒", "HA指令", "发现指令", song_name)
                        process_search_and_play(song_name)
        except Exception as e:
            pass
        time.sleep(2)


# ================= Flask 路由 =================
@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/stats')
def get_stats():
    """获取统计数据"""
    # === 核心修改点：不再计算百分比，直接返回具体的成功次数 ===
    return jsonify({
        "thread_active": system_status["thread_active"],
        "last_heartbeat": system_status["last_heartbeat"],
        "success_count": system_status["success_calls"],  # 前端字段名改为了 success_count
        "total_ops": system_status["total_calls"]
    })


@app.route('/api/logs')
def get_logs():
    logs = database.fetch_logs(limit=30)
    return jsonify(logs)


@app.route('/api/manual_exec', methods=['POST'])
def manual_exec():
    data = request.json
    song_name = data.get('song_name')
    if not song_name:
        return jsonify({"success": False, "msg": "请输入歌名"})

    database.insert_log("网页操作", "手动点歌", "处理中", song_name)
    result = process_search_and_play(song_name, source="web")
    return jsonify(result)


@app.route('/api/clear_logs', methods=['POST'])
def clear_logs():
    success = database.clear_all_logs()
    return jsonify({"success": success})


if __name__ == "__main__":
    database.init_db()
    monitor = threading.Thread(target=background_monitor, daemon=True)
    monitor.start()
    print("🚀 音乐服务器已启动... (已优化统计逻辑)")
    app.run(host='0.0.0.0', port=5000, debug=False)

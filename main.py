import requests
import time
import json
import os
import sys

# ================= 配置区域 (从环境变量读取) =================
# 格式：os.getenv("变量名", "默认值")
HA_URL = os.getenv("HA_URL", "http://192.168.1.X:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
PLAYER_ENTITY_ID = os.getenv("PLAYER_ENTITY_ID", "")
CONVERSATION_ENTITY_ID = os.getenv("CONVERSATION_ENTITY_ID", "")
MUSIC_SOURCE = os.getenv("MUSIC_SOURCE", "netease")
# ===========================================================

headers = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

# 解决 Docker 日志不显示的问题
def log(msg):
    print(msg)
    sys.stdout.flush()

def call_ha_service(domain, service, service_data):
    url = f"{HA_URL}/api/services/{domain}/{service}"
    try:
        requests.post(url, headers=headers, json=service_data, timeout=5)
    except Exception as e:
        log(f"HA调用失败: {e}")

def get_ha_state(entity_id):
    url = f"{HA_URL}/api/states/{entity_id}"
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json().get('state')
    except Exception as e:
        pass
    return None

def search_music(keyword):
    log(f"搜索: {keyword}")
    search_api = "https://music-api.gdstudio.xyz/api.php"
    params = {"types": "search", "count": 1, "source": MUSIC_SOURCE, "pages": 1, "name": keyword}
    try:
        res = requests.get(search_api, params=params, timeout=10).json()
        # 简单的结果提取逻辑
        if isinstance(res, list) and res: return res[0]
        if isinstance(res, dict) and 'list' in res and res['list']: return res['list'][0]
    except Exception as e:
        log(f"搜索API错误: {e}")
    return None

def get_music_url(song_id):
    url_api = "https://music-api.gdstudio.xyz/api.php"
    params = {"types": "url", "source": MUSIC_SOURCE, "id": song_id, "br": 320}
    try:
        res = requests.get(url_api, params=params, timeout=10).json()
        if res and 'url' in res: return res['url']
    except Exception as e:
        log(f"URL获取错误: {e}")
    return None

def main():
    log("--- 容器已启动 ---")
    log(f"HA地址: {HA_URL}")
    log(f"监听实体: {CONVERSATION_ENTITY_ID}")
    
    if not HA_TOKEN:
        log("错误: 未检测到 Token，请检查环境变量")
        return

    last_text = ""
    while True:
        try:
            current_text = get_ha_state(CONVERSATION_ENTITY_ID)
            if current_text and current_text != last_text:
                last_text = current_text
                trigger_word = "帮我搜"
                if current_text.startswith(trigger_word):
                    song_name = current_text.replace(trigger_word, "").strip()
                    log(f"收到指令: {song_name}")
                    
                    song_info = search_music(song_name)
                    if song_info:
                        log(f"找到: {song_info.get('name')} - {song_info.get('artist')}")
                        play_url = get_music_url(song_info.get('id'))
                        if play_url:
                            call_ha_service("media_player", "play_media", {
                                "entity_id": PLAYER_ENTITY_ID,
                                "media_content_id": play_url,
                                "media_content_type": "music"
                            })
                        else:
                            log("无播放链接")
                    else:
                        log("未找到歌曲")
        except Exception as e:
            log(f"主循环异常: {e}")
            time.sleep(5)
        time.sleep(2)

if __name__ == "__main__":
    main()

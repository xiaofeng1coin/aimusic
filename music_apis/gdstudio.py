import requests
import json
import re

# 维持独立的 Session
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://music-api.gdstudio.xyz/"
})

current_btwaf = "81051400"


def smart_request(url, params):
    global current_btwaf
    params['btwaf'] = current_btwaf
    try:
        resp = session.get(url, params=params, timeout=15)  # 稍微增加超时时间
        try:
            return resp.json()
        except json.JSONDecodeError:
            pass

        if "btwaf=" in resp.text:
            match = re.search(r'btwaf=(\d+)', resp.text)
            if match:
                new_btwaf = match.group(1)
                current_btwaf = new_btwaf
                params['btwaf'] = new_btwaf
                return session.get(url, params=params, timeout=15).json()
        return None
    except Exception as e:
        print(f"⚠️ [gdstudio] 网络请求异常: {e}")
        return None


def search(song_name):
    api_url = "https://music-api.gdstudio.xyz/api.php"
    params = {"types": "search", "count": 1, "source": "netease", "pages": 1, "name": song_name}
    res = smart_request(api_url, params)
    if res:
        if isinstance(res, list) and res:
            return res[0]
        elif isinstance(res, dict) and 'list' in res and res['list']:
            return res['list'][0]
    return None


def get_play_url(song_id):
    api_url = "https://music-api.gdstudio.xyz/api.php"
    params = {"types": "url", "source": "netease", "id": song_id, "br": 320}
    res = smart_request(api_url, params)
    if res and 'url' in res: return res['url']
    return None

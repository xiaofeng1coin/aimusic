import requests
import re
from urllib.parse import quote

# 创建 Session 保持连接
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Host": "www.6uq.cn",
    "Referer": "http://www.6uq.cn/",
    "Origin": "http://www.6uq.cn"
})

BASE_URL = "http://www.6uq.cn"


def search(song_name):
    """
    搜索歌曲，解析 HTML 提取歌曲 ID
    目标格式: <a href="http://www.6uq.cn/play/{id}.html" ...>...</a>
    """
    try:
        # 1. 发起搜索请求
        # 搜索URL: http://www.6uq.cn/so/{encoded_name}.html
        search_url = f"{BASE_URL}/so/{quote(song_name)}.html"

        resp = session.get(search_url, timeout=15)
        resp.encoding = 'utf-8'
        html = resp.text

        # 2. 正则匹配 ID 和 歌名
        # 示例: <div class="name"><a href="http://www.6uq.cn/play/d3Z3Zmpqd24.html" target="_mp3">G.E.M.&nbsp;邓紫棋《来自天堂的魔鬼》[MP3_LRC]</a></div>
        # 匹配 /play/ 和 .html 之间的字符串作为 ID
        pattern = r'class="name"><a href=".*?/play/([a-zA-Z0-9]+)\.html"[^>]*>(.*?)</a>'
        match = re.search(pattern, html, re.IGNORECASE)

        if match:
            song_id = match.group(1)
            raw_title = match.group(2)

            # 3. 清洗歌名
            # 去除 &nbsp;
            clean_title = raw_title.replace('&nbsp;', ' ')
            # 去除 HTML 标签
            clean_title = re.sub(r'<[^>]+>', '', clean_title)
            # 去除末尾的 [MP3_LRC] 等标记
            clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()

            return {
                "id": song_id,
                "name": clean_title,
                "artist": "未知",  # 搜索列表未分离歌手，通常包含在歌名中
                "source": "sixuq"  # 内部标识
            }
        return None
    except Exception as e:
        print(f"⚠️ [sixuq] 搜索异常: {e}")
        return None


def get_play_url(song_id):
    """
    通过 POST 接口获取播放链接
    URL: http://www.6uq.cn/js/play.php
    Body: id={song_id}&type=music
    """
    try:
        api_url = "http://www.6uq.cn/js/play.php"

        # 构造 POST 数据
        payload = {
            "id": song_id,
            "type": "music"
        }

        # 必要的请求头
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest"
        }

        # 发送 POST 请求
        resp = session.post(api_url, data=payload, headers=headers, timeout=10)

        # 解析 JSON
        data = resp.json()

        # 获取 url 字段
        if data and 'url' in data:
            play_url = data['url']
            if play_url:
                return play_url

        print(f"⚠️ [sixuq] 接口返回无 URL: {data}")
        return None

    except Exception as e:
        print(f"⚠️ [sixuq] 解析异常: {e}")
        return None

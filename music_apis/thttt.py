import requests
import re
from urllib.parse import quote

# 创建 Session 保持连接
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Host": "www.thttt.com",
    "Referer": "http://www.thttt.com/",
    "Origin": "http://www.thttt.com"
})

BASE_URL = "http://www.thttt.com"


def search(song_name):
    """
    搜索歌曲，解析 HTML 提取歌曲 ID
    目标格式: <a href="/mp3/{id}.html" ...>...</a>
    """
    try:
        # 1. 发起搜索请求
        search_url = f"{BASE_URL}/so.php?wd={quote(song_name)}"
        resp = session.get(search_url, timeout=15)
        resp.encoding = 'utf-8'  # 网页是 UTF-8
        html = resp.text

        # 2. 正则匹配 ID 和 歌名
        # 例子: <a href="/mp3/14261b97130ea1ced8d12a890bd1cb1a.html" class="url" target="_mp3">G.E.M. 邓紫棋 - <font color='red'>来自天堂的魔鬼</font></a>
        # 捕获组 1: ID
        # 捕获组 2: 歌名 (含HTML标签)
        pattern = r'href="/mp3/([a-f0-9]+)\.html"[^>]*>(.*?)</a>'
        match = re.search(pattern, html, re.IGNORECASE)

        if match:
            song_id = match.group(1)
            raw_title_html = match.group(2)

            # 清洗歌名中的 HTML 标签 (比如 <font color='red'>)
            clean_title = re.sub(r'<[^>]+>', '', raw_title_html).strip()

            return {
                "id": song_id,  # 提取出的 ID，例如 14261b97...
                "name": clean_title,  # 清洗后的歌名
                "artist": "未知",  # 搜索页没直接给歌手，暂填未知或包含在标题里
                "source": "thttt"
            }
        return None
    except Exception as e:
        print(f"⚠️ [thttt] 搜索异常: {e}")
        return None


def get_play_url(song_id):
    """
    通过 POST 接口获取播放链接
    URL: http://www.thttt.com/style/js/play.php
    Body: id={song_id}&type=dance
    """
    try:
        api_url = "http://www.thttt.com/style/js/play.php"

        # 构造 POST 数据
        payload = {
            "id": song_id,
            "type": "dance"
        }

        # 指定 Content-Type
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
            # 有些返回的 URL 可能是 http 开头，HA 可能需要 https (视情况而定，通常 http 也能播)
            # 但 thttt 返回的经常是 https 的 cdn 链接，直接返回即可
            if play_url:
                return play_url

        print(f"⚠️ [thttt] 接口返回无 URL: {data}")
        return None

    except Exception as e:
        print(f"⚠️ [thttt] 解析异常: {e}")
        return None

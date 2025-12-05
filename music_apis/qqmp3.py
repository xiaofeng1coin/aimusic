import requests
from urllib.parse import quote

# 定义通用请求头
# 虽然你说只要Host，但为了稳定性，加上 User-Agent 是标准操作
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    # requests 会自动处理 Host，通常不需要手动写
}


def search(song_name):
    """
    搜索逻辑
    URL: https://api.qqmp3.vip/api/songs.php?type=search&keyword={歌名}
    """
    try:
        # 1. 编码歌名
        keyword = quote(song_name)
        url = f"https://api.qqmp3.vip/api/songs.php?type=search&keyword={keyword}"

        # 2. 发送请求
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()

        # 3. 解析数据
        # 结构: data['data'][0] -> rid, name, artist
        if data.get('code') == 200 and data.get('data'):
            first_song = data['data'][0]

            return {
                "id": first_song.get('rid'),  # 获取 rid (例如 564)
                "name": first_song.get('name'),  # 获取歌名
                "artist": first_song.get('artist'),  # 获取歌手
                "source": "qqmp3"
            }

        return None

    except Exception as e:
        print(f"⚠️ [qqmp3] 搜索报错: {e}")
        return None


def get_play_url(song_id):
    """
    解析逻辑
    URL: https://api.qqmp3.vip/api/kw.php?rid={id}&type=json&level=exhigh&lrc=true
    """
    try:
        # 构造 URL
        url = f"https://api.qqmp3.vip/api/kw.php?rid={song_id}&type=json&level=exhigh&lrc=true"

        # 发送请求
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()

        # 解析数据
        # 结构: data['data']['url']
        if data.get('code') == 200 and data.get('data'):
            play_url = data['data'].get('url')

            # 简单的有效性校验
            if play_url and play_url.startswith("http"):
                return play_url

        print(f"⚠️ [qqmp3] 未找到播放链接: {data}")
        return None

    except Exception as e:
        print(f"⚠️ [qqmp3] 解析报错: {e}")
        return None

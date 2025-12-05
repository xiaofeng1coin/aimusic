import concurrent.futures
import random
import time
from . import gdstudio
from . import thttt
from . import uq6
from . import qqmp3

# 注册所有可用驱动
DRIVERS = {
    "gdstudio": gdstudio,
    "thttt": thttt,
    "uq6": uq6,
    "qqmp3": qqmp3
}


def _single_driver_task(driver_name, driver_module, song_name):
    """单个驱动的工作线程 (保持不变)"""
    start_time = time.time()
    try:
        song_info = driver_module.search(song_name)
        if not song_info:
            return {"success": False, "source": driver_name, "msg": "搜索无结果",
                    "duration": int((time.time() - start_time) * 1000)}

        play_url = driver_module.get_play_url(song_info['id'])
        if play_url:
            song_info['source_label'] = driver_name
            return {"success": True, "source": driver_name, "info": song_info, "url": play_url,
                    "duration": int((time.time() - start_time) * 1000)}
        else:
            return {"success": False, "source": driver_name, "msg": "无法解析播放链接",
                    "duration": int((time.time() - start_time) * 1000)}

    except Exception as e:
        return {"success": False, "source": driver_name, "msg": f"程序异常: {str(e)}",
                "duration": int((time.time() - start_time) * 1000)}


def search_and_get_url(song_name, source="all"):
    """
    修改后：支持 source 为逗号分隔的字符串，例如 "gdstudio,qqmp3"
    """
    target_drivers = {}

    # === 修改逻辑开始 ===
    if not source or source == "all":
        target_drivers = DRIVERS
    else:
        # 将 "gdstudio,qqmp3" 分割并过滤
        selected_keys = source.split(',')
        for key in selected_keys:
            key = key.strip()
            if key in DRIVERS:
                target_drivers[key] = DRIVERS[key]

    # 如果用户选的源都不存在（比如拼写错误），回退到默认全部
    if not target_drivers:
        target_drivers = DRIVERS
    # === 修改逻辑结束 ===

    print(f"🔥 [并发启动] 目标源: {list(target_drivers.keys())} | 搜索: {song_name}")

    success_results = []
    error_logs = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(target_drivers) + 2) as executor:
        future_to_source = {
            executor.submit(_single_driver_task, name, module, song_name): name
            for name, module in target_drivers.items()
        }

        for future in concurrent.futures.as_completed(future_to_source):
            driver_name = future_to_source[future]
            try:
                res = future.result()
                if res['success']:
                    print(f"✅ [{driver_name}] 成功 ({res['duration']}ms)")
                    success_results.append(res)
                else:
                    # print(f"❌ [{driver_name}] 失败: {res['msg']}") # 减少控制台刷屏
                    error_logs.append({"source": driver_name, "msg": res['msg'], "duration": res['duration']})
            except Exception as exc:
                print(f"❌ [{driver_name}] 线程崩溃: {exc}")
                error_logs.append({"source": driver_name, "msg": f"CRASH: {str(exc)}", "duration": 0})

    if not success_results:
        return False, "所有选定音源均未找到可用链接", None, None, error_logs

    final_choice = random.choice(success_results)
    return True, "成功", final_choice['info'], final_choice['url'], error_logs

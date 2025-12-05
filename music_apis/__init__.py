import concurrent.futures
import time
import sys

# 引入同目录下的驱动模块
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
    """单个驱动的工作线程"""
    start_time = time.time()
    try:
        # 1. 搜索
        song_info = driver_module.search(song_name)
        if not song_info:
            return {
                "success": False, 
                "source": driver_name, 
                "msg": "搜索无结果",
                "duration": int((time.time() - start_time) * 1000)
            }

        # 2. 获取链接
        play_url = driver_module.get_play_url(song_info['id'])
        if play_url:
            song_info['source_label'] = driver_name
            return {
                "success": True, 
                "source": driver_name, 
                "info": song_info, 
                "url": play_url,
                "duration": int((time.time() - start_time) * 1000)
            }
        else:
            return {
                "success": False, 
                "source": driver_name, 
                "msg": "无法解析播放链接",
                "duration": int((time.time() - start_time) * 1000)
            }

    except Exception as e:
        return {
            "success": False, 
            "source": driver_name, 
            "msg": f"程序异常: {str(e)}",
            "duration": int((time.time() - start_time) * 1000)
        }


def search_and_get_url(song_name, source="all"):
    """
    并发搜索：竞速模式 (Race Mode)
    一旦有一个源成功获取到 URL，立即返回，不再等待其他源。
    """
    # 1. 确定目标驱动
    target_drivers = {}
    if not source or source == "all":
        target_drivers = DRIVERS
    else:
        selected_keys = source.split(',')
        for key in selected_keys:
            key = key.strip()
            if key in DRIVERS:
                target_drivers[key] = DRIVERS[key]
    
    if not target_drivers:
        target_drivers = DRIVERS

    # 打印极速搜索日志
    source_list = list(target_drivers.keys())
    print(f"🔥 [极速搜索] 目标源: {source_list} | 歌名: {song_name}")

    error_logs = []
    
    # 不使用 'with'，允许立即返回而不阻塞
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(target_drivers) + 2)
    
    try:
        # 提交所有任务
        future_to_source = {
            executor.submit(_single_driver_task, name, module, song_name): name
            for name, module in target_drivers.items()
        }

        # 循环检查完成的任务
        for future in concurrent.futures.as_completed(future_to_source):
            driver_name = future_to_source[future]
            try:
                res = future.result()
                if res['success']:
                    # 🎯 命中：打印率先胜出日志
                    print(f"🚀 [率先胜出] {driver_name} ({res['duration']}ms)")
                    
                    # 停止接收新任务，不等待其他任务
                    executor.shutdown(wait=False)
                    
                    return True, "成功", res['info'], res['url'], error_logs
                else:
                    # 失败了记录日志，但不打印，保持控制台清爽
                    error_logs.append({"source": driver_name, "msg": res['msg'], "duration": res['duration']})
            
            except Exception as exc:
                # print(f"❌ [{driver_name}] 线程崩溃: {exc}")
                error_logs.append({"source": driver_name, "msg": f"CRASH: {str(exc)}", "duration": 0})

    finally:
        # 确保最终关闭线程池资源
        executor.shutdown(wait=False)

    # 如果循环结束还没有 return，说明所有源都失败了
    print(f"❌ [搜索结束] 所有源均未返回有效结果")
    return False, "所有选定音源均未找到可用链接", None, None, error_logs

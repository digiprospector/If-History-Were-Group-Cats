import os
import json
import re
import shutil
import argparse
from pathlib import Path

# ==========================================
# 配置选项 (Configuration)
# ==========================================
# 是否在重命名后的文件名前加上章节序号 (例如: "01 华夏诞生.mp4")
# 如果为 False，则严格按照 titles.json 中的名字 (例如: "华夏诞生.mp4")
ADD_INDEX_PREFIX = False

# 是否在重命名后的目录名前加上季数序号 (例如: "第01季 夏商西周")
# 如果为 False，则严格按照 titles.json 中的名字 (例如: "夏商西周")
ADD_SEASON_PREFIX = False
# ==========================================

def get_last_num(path_obj):
    """提取文件名中的最后一个数字，用于正确排序"""
    nums = re.findall(r'\d+', path_obj.name)
    return int(nums[-1]) if nums else 0

def main():
    parser = argparse.ArgumentParser(description='根据 titles.json 链接或复制视频文件')
    parser.add_argument('-c', '--copy', action='store_true', help='使用复制 (copy) 而不是符号链接')
    parser.add_argument('-d', '--dry', action='store_true', help='演练模式 (dry run)，仅打印操作，不实际修改文件系统')
    args = parser.parse_args()

    titles_path = Path('titles.json')
    if not titles_path.exists():
        print("错误: 当前目录下找不到 titles.json 文件！")
        return

    with open(titles_path, 'r', encoding='utf-8') as f:
        titles_data = json.load(f)
    
    episodes = titles_data.get('episodes', [])
    
    # 建立季数 (从1开始) 到 季信息的映射
    season_data = {}
    for i, ep in enumerate(episodes, 1):
        season_data[i] = ep

    base_dir = Path('.')
    
    # 遍历当前目录下的所有子目录
    for item in base_dir.iterdir():
        if not item.is_dir():
            continue
            
        # 匹配目录名，如 "第1-3季", "第7季", "第10季 宋辽金夏篇"
        m = re.search(r'第(\d+)(?:-(\d+))?季', item.name)
        if not m:
            continue
            
        start_s = int(m.group(1))
        end_s = int(m.group(2)) if m.group(2) else start_s
        
        # 收集该目录下的所有 mp4 文件
        mp4_files = list(item.rglob('*.mp4'))
        if not mp4_files:
            continue
            
        # 根据文件名中的最后一个数字进行排序
        # 这样能保证 EP138...01, EP146...09, 10, 11, 12 这样的文件顺序正确
        mp4_files.sort(key=get_last_num)
        
        # 根据映射的季数，收集目标章节名称
        target_chapters = []
        for s in range(start_s, end_s + 1):
            if s in season_data:
                s_title = season_data[s]['title']
                for ch_idx, ch_name in enumerate(season_data[s]['chapters'], 1):
                    target_chapters.append({
                        'season_num': s,
                        'season_title': s_title,
                        'chapter_idx': ch_idx,
                        'chapter_name': ch_name
                    })
                    
        # 处理文件
        # zip() 会安全地匹配文件和目标章节（多余的章节会被忽略，适应动画版合并章节的情况）
        for fpath, target in zip(mp4_files, target_chapters):
            s_num = target['season_num']
            s_title = target['season_title']
            c_name = target['chapter_name']
            c_idx = target['chapter_idx']
            
            # 确定新的目录名称
            dir_name = f"第{s_num:02d}季 {s_title}" if ADD_SEASON_PREFIX else s_title
            
            # 确定新的文件名称
            file_name = f"{c_idx:02d} {c_name}.mp4" if ADD_INDEX_PREFIX else f"{c_name}.mp4"
            
            new_dir = base_dir / dir_name
            if not args.dry:
                new_dir.mkdir(parents=True, exist_ok=True)
            
            new_file = new_dir / file_name
            
            if new_file.exists():
                print(f"跳过: 目标文件已存在 '{new_file}'")
                continue
                
            prefix = "[DRY RUN] " if args.dry else ""
            if args.copy:
                print(f"{prefix}复制并重命名: '{fpath}' -> '{new_file}'")
                if not args.dry:
                    shutil.copy2(fpath, new_file)
            else:
                print(f"{prefix}创建符号链接: '{fpath}' -> '{new_file}'")
                if not args.dry:
                    try:
                        os.symlink(fpath.absolute(), new_file)
                    except OSError as e:
                        print(f"  [失败] 无法创建符号链接 ({e})。在 Windows 上可能需要管理员权限或开启开发者模式。")
            
    print("\n所有文件操作完成！")

if __name__ == '__main__':
    main()

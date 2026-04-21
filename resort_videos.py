import os
import json
import re
import shutil
import argparse
from pathlib import Path



def get_last_num(path_obj):
    """提取文件名中的最后一个数字，用于正确排序"""
    nums = re.findall(r'\d+', path_obj.stem)
    return int(nums[-1]) if nums else 0

def main():
    parser = argparse.ArgumentParser(description='根据 episode_titles.json 链接或复制视频文件')
    parser.add_argument('-c', '--copy', action='store_true', help='使用复制 (copy) 而不是符号链接')
    parser.add_argument('-d', '--dst', default=None, help='指定目标输出目录 (默认为源目录)')
    parser.add_argument('-D', '--dry', action='store_true', help='演练模式 (dry run)，仅打印操作，不实际修改文件系统')
    parser.add_argument('-s', '--src', default='.', help='指定包含源视频文件和 episode_titles.json 的源目录 (默认为当前目录)')
    args = parser.parse_args()

    base_dir = Path(args.src)
    dst_dir = Path(args.dst) if args.dst else base_dir
    
    dry_run_stats = {
        "match": 0,
        "mismatch": [],
        "no_chinese_src": []
    }
    titles_path = base_dir / 'episode_titles.json'
    if not titles_path.exists():
        # 回退：如果源目录里没有，尝试在当前执行目录找
        titles_path = Path('episode_titles.json')
        if not titles_path.exists():
            print(f"错误: 找不到 episode_titles.json 文件！请确保在 {base_dir} 或当前目录下有此文件。")
            return

    with open(titles_path, 'r', encoding='utf-8') as f:
        titles_data = json.load(f)
    
    episodes = titles_data.get('episodes', [])
    
    # 建立季数 (从1开始) 到 季信息的映射
    season_data = {}
    for i, ep in enumerate(episodes, 1):
        season_data[i] = ep
    
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
            dir_name = f"{s_num:02d}. {s_title}"
            
            # 确定新的文件名称
            file_name = f"{c_idx:02d}. {c_name}.mp4"
            
            new_dir = dst_dir / dir_name
            if not args.dry:
                new_dir.mkdir(parents=True, exist_ok=True)
            
            new_file = new_dir / file_name
            
            if new_file.exists():
                print(f"跳过: 目标文件已存在 '{new_file}'")
                continue
                
            prefix = "[DRY RUN] " if args.dry else ""
            if args.copy:
                print(f"{prefix}把 '{fpath}' 复制到 '{new_file}'")
                if not args.dry:
                    shutil.copy2(fpath, new_file)
            else:
                print(f"{prefix}把 '{fpath}' 链接到 '{new_file}'")
                if not args.dry:
                    try:
                        os.symlink(fpath.absolute(), new_file)
                    except OSError as e:
                        print(f"  [失败] 无法创建符号链接 ({e})。在 Windows 上可能需要管理员权限或开启开发者模式。")
                        
            if args.dry:
                src_cn = "".join(re.findall(r'[\u4e00-\u9fa5]+', fpath.stem))
                dst_cn = "".join(re.findall(r'[\u4e00-\u9fa5]+', c_name))
                if not src_cn:
                    dry_run_stats["no_chinese_src"].append(str(fpath))
                else:
                    if src_cn == dst_cn:
                        dry_run_stats["match"] += 1
                    else:
                        dry_run_stats["mismatch"].append((str(fpath), src_cn, dst_cn))
            
    print("\n所有文件操作完成！")
    
    if args.dry:
        print("\n=== DRY RUN 汉字匹配统计 ===")
        print(f"匹配成功: {dry_run_stats['match']} 个文件")
        if dry_run_stats['mismatch']:
            print(f"匹配不一致 ({len(dry_run_stats['mismatch'])} 个):")
            for p, s, d in dry_run_stats['mismatch']:
                print(f"  文件: {p}")
                print(f"    源汉字: {s}")
                print(f"    目标汉字: {d}")
        if dry_run_stats['no_chinese_src']:
            print(f"源文件无汉字 ({len(dry_run_stats['no_chinese_src'])} 个):")
            for p in dry_run_stats['no_chinese_src']:
                print(f"  {p}")

if __name__ == '__main__':
    main()

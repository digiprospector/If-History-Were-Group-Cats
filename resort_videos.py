import os
import sys
import io
import json
import re
import shutil
import argparse
from pathlib import Path

def get_last_num(name):
    """提取字符串中的最后一个数字，用于正确排序"""
    nums = re.findall(r'\d+', name)
    return int(nums[-1]) if nums else 0

def extract_chinese(text):
    return "".join(re.findall(r'[\u4e00-\u9fa5]+', text))

def process_local(args, season_data, dry_run_stats):
    base_dir = Path(args.src)
    dst_dir = Path(args.dst) if args.dst else base_dir

    for item in base_dir.iterdir():
        if not item.is_dir():
            continue
            
        m = re.search(r'第?(\d+)(?:-(\d+))?季', item.name)
        if not m:
            continue
            
        start_s = int(m.group(1))
        end_s = int(m.group(2)) if m.group(2) else start_s
        
        video_files = [p for p in item.rglob('*') if p.suffix.lower() in ('.mp4', '.mkv')]
        if not video_files:
            continue
            
        video_files.sort(key=lambda p: get_last_num(p.stem))
        
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
                    
        for fpath, target in zip(video_files, target_chapters):
            s_num = target['season_num']
            s_title = target['season_title']
            c_name = target['chapter_name']
            c_idx = target['chapter_idx']
            
            dir_name = f"{s_num:02d}. {s_title}"
            file_name = f"{c_idx:02d}. {c_name}{fpath.suffix}"
            
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
                src_cn = extract_chinese(fpath.stem)
                dst_cn = extract_chinese(c_name)
                if not src_cn:
                    dry_run_stats["no_chinese_src"].append(str(fpath))
                else:
                    if src_cn == dst_cn:
                        dry_run_stats["match"] += 1
                    else:
                        dry_run_stats["mismatch"].append((str(fpath), src_cn, dst_cn))

def get_all_quark_files(client, folder_id):
    files = []
    page = 1
    while True:
        try:
            resp = client.list_files(folder_id, page=page, size=100)
            items = resp.get("data", {}).get("list", [])
        except Exception:
            items = []
        if not items:
            break
        files.extend(items)
        if len(items) < 100:
            break
        page += 1
    return files

def process_quark(args, season_data, dry_run_stats):
    if sys.platform == 'win32' and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        except Exception:
            pass

    try:
        from quark_client import QuarkClient
    except ImportError:
        print("错误: 缺少 quarkpan 库。请先运行 'pip install quarkpan'")
        return

    client = QuarkClient()
    if not client.is_logged_in():
        client.login()

    try:
        src_folder_id, file_type = client.resolve_path(args.src)
    except Exception as e:
        print(f"获取源目录失败: {e}。请确保指定的源目录路径在夸克网盘存在 (如 '/B站/如果历史是一群喵')")
        return

    if file_type != "folder":
        print("源目录路径解析错误：是一个文件")
        return

    dst_folder_path = args.dst if args.dst else args.src
    # 尝试解析目标目录，如果不存在，尝试在根目录查找或报错
    try:
        dst_folder_id, _ = client.resolve_path(dst_folder_path)
    except Exception:
        print(f"目标目录 '{dst_folder_path}' 在网盘上不存在。夸克网盘模式下，目标目录路径必须存在。请手动在网盘上创建。")
        return

    print(f"成功连接夸克网盘。正在遍历目录...")
    items = get_all_quark_files(client, src_folder_id)
    print(f"[DEBUG] 在源目录 (ID: {src_folder_id}) 中查找到 {len(items)} 个项目")
    
    dir_id_cache = {}

    for item in items:
        # QuarkAPI返回 file_type 或者 dir标识
        is_dir = item.get('dir', False)
        if not is_dir:
            continue
        
        dir_name = item.get("file_name", "")
        print(f"[DEBUG] 季目录: {dir_name}")
        m = re.search(r'第?(\d+)(?:-(\d+))?季', dir_name)
        if not m:
            continue
        
        print(f"[DEBUG] 匹配到季目录: {dir_name}")
        start_s = int(m.group(1))
        end_s = int(m.group(2)) if m.group(2) else start_s
        
        sub_items = get_all_quark_files(client, item.get("fid"))
        print(f"[DEBUG] 目录 '{dir_name}' 中包含 {len(sub_items)} 个项目")
        video_files = [f for f in sub_items if str(f.get("file_name", "")).lower().endswith((".mp4", ".mkv"))]
        
        if video_files:
            print(f"[DEBUG] 目录 '{dir_name}' 中找到 {len(video_files)} 个视频文件")
            video_files.sort(key=lambda x: get_last_num(x.get("file_name", "")))
            
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
                        
            for f, target in zip(video_files, target_chapters):
                s_num = target['season_num']
                s_title = target['season_title']
                c_name = target['chapter_name']
                c_idx = target['chapter_idx']
                
                f_name = f.get("file_name", "")
                f_id = f.get("fid")
                ext = os.path.splitext(f_name)[1]
                
                new_dir_name = f"{s_num:02d}. {s_title}"
                new_file_name = f"{c_idx:02d}. {c_name}{ext}"
                
                prefix = "[DRY RUN] " if args.dry else ""
                print(f"{prefix}把夸克文件 '{f_name}' 移动并重命名为 '{new_dir_name}/{new_file_name}'")
                
                if not args.dry:
                    new_dir_id = dir_id_cache.get(new_dir_name)
                    if not new_dir_id:
                        # 尝试创建
                        try:
                            res = client.create_folder(new_dir_name, parent_id=dst_folder_id)
                            new_dir_id = res.get("data", {}).get("fid", "")
                            dir_id_cache[new_dir_name] = new_dir_id
                        except Exception:
                            # 失败则说明可能存在，尝试解析
                            try:
                                dst_full = dst_folder_path.rstrip("/") + "/" + new_dir_name
                                new_dir_id, _ = client.resolve_path(dst_full)
                                dir_id_cache[new_dir_name] = new_dir_id
                            except Exception as e2:
                                print(f"  [失败] 无法创建或获取目录 '{new_dir_name}': {e2}")
                                continue
                    
                    # Quark要求重命名不能带有 /。重命名后通过 move_files 移动
                    try:
                        client.rename_file(f_id, new_file_name)
                    except Exception as e:
                        print(f"  [失败] 重命名文件失败 '{f_name}'->'{new_file_name}': {e}")
                        
                    try:
                        client.move_files([f_id], new_dir_id)
                    except Exception as e:
                        print(f"  [失败] 移动文件失败 '{new_file_name}': {e}")
                
                if args.dry:
                    src_cn = extract_chinese(f_name.replace(".mp4", ""))
                    dst_cn = extract_chinese(c_name)
                    if not src_cn:
                        dry_run_stats["no_chinese_src"].append(f_name)
                    else:
                        if src_cn == dst_cn:
                            dry_run_stats["match"] += 1
                        else:
                            dry_run_stats["mismatch"].append((f_name, src_cn, dst_cn))
        else:
            print(f"[DEBUG] 目录 '{dir_name}' 中没有找到视频文件")

        # 检查是否需要删除空目录
        if not args.dry:
            try:
                # 重新检查目录内容，确认是否已清空
                remaining = get_all_quark_files(client, item.get("fid"))
                if not remaining:
                    print(f"删除已清空的源目录: {dir_name}")
                    client.delete_files([item.get("fid")])
            except Exception as e:
                print(f"  [失败] 无法检查或删除目录 '{dir_name}': {e}")
        else:
            # 在 dry run 中，我们检查 sub_items 或 video_files 来模拟
            if not sub_items or (video_files and len(sub_items) == len(video_files)):
                print(f"[DRY RUN] 将删除已清空的源目录: {dir_name}")


def main():
    parser = argparse.ArgumentParser(description='根据 episode_titles.json 链接或复制视频文件（支持夸克网盘）')
    parser.add_argument('-c', '--copy', action='store_true', help='(仅本地) 使用复制 (copy) 而不是符号链接')
    parser.add_argument('-d', '--dst', default=None, help='指定目标输出目录 (默认为源目录)')
    parser.add_argument('-D', '--dry', action='store_true', help='演练模式 (dry run)，仅打印操作，不实际修改文件系统')
    parser.add_argument('-s', '--src', default='.', help='指定包含源视频文件的源目录 (默认为当前目录)')
    parser.add_argument('--quark', action='store_true', help='启用夸克网盘模式 (将直接连接云盘进行移动和重命名)')
    args = parser.parse_args()

    # titles.json 是本地读取的
    base_dir = Path(args.src if not args.quark else '.')
    titles_path = base_dir / 'episode_titles.json'
    if not titles_path.exists():
        titles_path = Path('episode_titles.json')
        if not titles_path.exists():
            print(f"错误: 找不到 episode_titles.json 文件！请确保在当前目录下有此文件。")
            return

    with open(titles_path, 'r', encoding='utf-8') as f:
        titles_data = json.load(f)
    
    episodes = titles_data.get('episodes', [])
    season_data = {}
    for i, ep in enumerate(episodes, 1):
        season_data[i] = ep

    dry_run_stats = {
        "match": 0,
        "mismatch": [],
        "no_chinese_src": []
    }

    if args.quark:
        process_quark(args, season_data, dry_run_stats)
    else:
        process_local(args, season_data, dry_run_stats)

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

# 如果历史是一群喵

从 Bilibili 番剧接口抓取《如果历史是一群喵》的分组章节标题数据。

脚本默认只输出 JSON；仅在显式传入 `--csv` 时才生成 CSV。

## 环境要求

- Python 3.10+

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

## 运行方式

默认运行（使用 `https://www.bilibili.com/bangumi/play/ss25469`）：

```bash
python bili_episode_titles.py
```

常用参数：

- `-u, --url`：番剧 URL 或 `season_id`
- `--json`：JSON 输出路径（默认 `episode_titles.json`）
- `--csv`：可选 CSV 输出路径（默认不生成）
- `--include-section`：包含 `section` 中的扩展分集
- `--timeout`：HTTP 超时秒数（默认 `20`）
- `--retry`：单请求重试次数（默认 `3`）

示例：

```bash
python bili_episode_titles.py --url https://www.bilibili.com/bangumi/play/ss25469 --json out.json
python bili_episode_titles.py --url 25469 --csv out.csv
```

## JSON 结构

输出顶层键为 `episodes`：

```json
{
  "episodes": [
    {
      "title": "分组标题",
      "chapters": ["章节1", "章节2"]
    }
  ]
}
```

## `titles.json` 参考规则

仅当输入 URL 的路径为 `/bangumi/play/ss25469`（例如 `https://www.bilibili.com/bangumi/play/ss25469`）时，才会参考 `titles.json`。

启用后规则：

1. 前 5 个分组的 `title` 使用 `titles.json` 对应项。
2. 前 5 个分组的 `chapters` 数量与 `titles.json` 对应项一致。
3. 章节内容优先使用网站抓取值；网站缺失时回退到 `titles.json`。

对于其他 URL 或纯 `season_id` 输入，不参考 `titles.json`。


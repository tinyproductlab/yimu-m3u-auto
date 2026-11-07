# 一幕播单

把多路公开 M3U 源收进来，加工成一份属于自己的订阅清单，供一幕各端订阅。

## 流水线

定时拉取（失败自动回退上一版缓存）→ 解析 → 去重（按 tvg-id/台名，源优先级高者优先，同源偏好 https；源缺 tvg-id 时用 tvg-name 补）→ 可选验活 → 输出 `out/merged.m3u`；同时按各源声明的 `x-tvg-url`（或 sources.json 里给源额外配的 `epg` 字段）合并 XMLTV，命中频道的 id 会改写成清单里实际用的 tvg-id，输出 `out/epg.xml`，并把引用写回清单头。

## 用法

```
python3 aggregate.py              # 完整跑：拉取 + 去重 + 验活 + 生成
python3 aggregate.py --no-check   # 跳过验活，快速生成
python3 aggregate.py --timeout 5 --workers 64   # 调验活参数
```

源在 `sources.json` 里配：name、url、priority（数字小优先）、可选 epg 数组。产物在 `out/`：`merged.m3u`、`epg.xml`、`report.json`（每路源的条数、验活结果、EPG 命中数）。

## 当前内置源

- fanmingming（CCTV＋卫视，带台标，优先级最高）
- iptv-org 中国区
- YanG-1989 聚合

## 已知限制（v1 实测）

- **验活必须在国内网络跑**：云端海外出口测国内流大量 403（属地限制），结果全灭不代表源死了。在家里 Mac/NAS 上跑验活才准；云端跑请加 `--no-check`。
- fanmingming 清单头里声明的 EPG 地址已在源站 404，EPG 合并逻辑就绪，等任一路带可用 EPG 的源接通即自动绑定（YanG 的 EPG 在其清单头里，从国内网络拉通后生效）。
- 跨源同台不同名（如 CCTV 1 与 CCTV-1）v1 不做模糊合并，可能各留一条；同源内已去重。
- #EXTVLCOPT 等附加头暂不保留（这类源占比极低）。

## 自动发布

公开入口：https://m3u.tinyplab.com/

GitHub Actions 每 6 小时尝试更新，也可在 Actions 页面手动运行「定时聚合播单」。
流程在云端使用 `--no-check`，生成全量、央视卫视、体育、少儿和电影订阅，并把清单、来源报告与最近一次有效的源缓存提交到仓库。上游返回错误或空清单时使用该源缓存；无任何可用频道时保留上一版站点。

仓库的 Settings → Pages → Source 选择 GitHub Actions，Custom domain 设置为 `m3u.tinyplab.com`。在 Cloudflare 的 `tinyplab.com` 区域添加 DNS only 的 CNAME：`m3u` → `tinyproductlab.github.io`。等 GitHub Pages 签发证书后启用 Enforce HTTPS。

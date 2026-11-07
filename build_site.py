#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 out/merged.m3u 拆成子清单并生成 m3u.tinyplab.com 的静态展示页 -> out/site/
先跑 aggregate.py 生成 merged.m3u，再跑本脚本。
"""
import json, re, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
SITE = BASE / "out" / "site"
DOMAIN = "https://m3u.tinyplab.com"

def parse_entries(text):
    entries, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
            cur = {"line": line, "group": attrs.get("group-title", ""), "name": line.rsplit(",", 1)[-1].strip()}
        elif line and not line.startswith("#") and cur is not None:
            cur["url"] = line
            entries.append(cur)
            cur = None
    return entries

def write_list(filename, entries, has_epg):
    head = f'#EXTM3U x-tvg-url="{DOMAIN}/epg.xml"' if has_epg else "#EXTM3U"
    body = []
    for e in entries:
        body.append(e["line"])
        body.append(e["url"])
    (SITE / filename).write_text("\n".join([head] + body) + "\n", encoding="utf-8")
    return len(entries)

def main():
    merged_path = BASE / "out" / "merged.m3u"
    report = json.loads((BASE / "out" / "report.json").read_text(encoding="utf-8"))
    entries = parse_entries(merged_path.read_text(encoding="utf-8"))
    SITE.mkdir(parents=True, exist_ok=True)
    epg_src = BASE / "out" / "epg.xml"
    has_epg = epg_src.exists() and report.get("epg", {}).get("channels", 0) > 0
    if has_epg:
        shutil.copy(epg_src, SITE / "epg.xml")
    else:
        (SITE / "epg.xml").unlink(missing_ok=True)

    def has(*words, in_name=False):
        def f(e):
            hay = (e["group"] + " " + (e["name"] if in_name else "")).lower()
            return any(w.lower() in hay for w in words)
        return f

    rules = [
        ("cctv.m3u", "央视＋卫视", lambda e: e["group"] in ("央视", "卫视") or e["name"].upper().startswith("CCTV") or "卫视" in e["name"]),
        ("sports.m3u", "体育", has("sports", "体育", in_name=True)),
        ("kids.m3u", "少儿卡通", has("kids", "animation", "少儿", "卡通", "动画", in_name=True)),
        ("movies.m3u", "电影", has("movies", "电影", "影院", in_name=True)),
    ]
    lists = []
    n_all = write_list("all.m3u", entries, has_epg)
    lists.append(("all.m3u", "全量合集（央视/卫视/地方/体育/少儿…）", "一幕播单·全量", n_all))
    short_names = {"cctv.m3u": "一幕播单·央视卫视", "sports.m3u": "一幕播单·体育", "kids.m3u": "一幕播单·少儿", "movies.m3u": "一幕播单·电影"}
    for fn, label, rule in rules:
        sub = [e for e in entries if rule(e)]
        n = write_list(fn, sub, has_epg)
        lists.append((fn, label, short_names.get(fn, label), n))
        print(f"{fn}: {n}")

    cards = "\n".join(
        f'''<div class="card"><div class="meta"><div class="name">{label}<button class="mini copy-name" data-copy="{short}">复制名字</button></div><div class="cnt">{n} 个频道 · 文件 {fn}</div></div><div class="row"><code>{DOMAIN}/{fn}</code><button data-copy="{DOMAIN}/{fn}">复制地址</button></div></div>'''
        for fn, label, short, n in lists
    )
    epg_card = ""
    if has_epg:
        epg_card = f'''<div class="card"><div class="meta"><div class="name">EPG 节目单<button class="mini copy-name" data-copy="一幕播单·节目单">复制名字</button></div><div class="cnt">{report["epg"]["channels"]} 个频道 · {report["epg"]["programmes"]} 条节目</div></div><div class="row"><code>{DOMAIN}/epg.xml</code><button data-copy="{DOMAIN}/epg.xml">复制地址</button></div></div>'''
    else:
        epg_card = '''<div class="card dim"><div class="meta"><div class="name">EPG 节目单</div><div class="cnt">节目单源完善中，稍后上线</div></div></div>'''

    products = '''<h2 class="ptitle">小产品实验室的其他产品</h2>
<div class="prods">
<a href="https://tinylabpro.com/tools/" target="_blank" rel="noopener">选字转二维码插件<i>选中文字右键生成二维码</i></a>
<a href="https://renguanwang.com" target="_blank" rel="noopener">认官网<i>认准官网，访问不迷路</i></a>
<a href="https://keyscan.tinylabpro.com/" target="_blank" rel="noopener">KeyScan<i>本地密码管理与验证器</i></a>
<a href="https://nconvo.tinylabpro.com" target="_blank" rel="noopener">NConvo<i>隐私网络工具箱</i></a>
<a href="https://catbox.gugujoy.com" target="_blank" rel="noopener">猫猫纸箱<i>600 关猫咪解谜小游戏</i></a>
<a href="https://tinylabpro.com" target="_blank" rel="noopener">全部产品<i>小产品实验室主站</i></a>
</div>'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>一幕播单 · 免费直播频道订阅地址</title>
<meta name="description" content="自动维护的公开免费直播频道 M3U 订阅地址，一键复制，适用于任何支持 M3U 的播放器。">
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#0f1115;color:#e8eaed}}
.wrap{{max-width:720px;margin:0 auto;padding:32px 16px 48px}}
h1{{font-size:26px;margin:0 0 8px}}
.sub{{color:#9aa0a6;line-height:1.7;margin:0 0 6px}}
.stats{{color:#e8eaed;background:#171a21;border:1px solid #232833;border-radius:10px;padding:10px 14px;margin:16px 0 24px;font-size:14px}}
.card{{background:#171a21;border:1px solid #232833;border-radius:12px;padding:16px;margin:0 0 12px}}
.card.dim{{opacity:.55}}
.name{{font-size:17px;font-weight:600}}
.cnt{{color:#9aa0a6;font-size:13px;margin-top:2px}}
.row{{display:flex;gap:8px;margin-top:12px}}
code{{flex:1;background:#0f1115;border:1px solid #232833;border-radius:8px;padding:9px 10px;font-size:13px;overflow-x:auto;white-space:nowrap}}
button{{background:#d93025;color:#fff;border:0;border-radius:8px;padding:0 18px;font-size:14px;cursor:pointer}}
button.ok{{background:#188038}}
button.mini{{background:transparent;border:1px solid #3a4152;color:#9aa0a6;border-radius:6px;padding:2px 10px;font-size:12px;margin-left:10px;vertical-align:2px}}
button.mini.ok{{background:#188038;color:#fff;border-color:#188038}}
.ptitle{{font-size:18px;margin:28px 0 12px}}
.prods{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.prods a{{background:#171a21;border:1px solid #232833;border-radius:10px;padding:12px 14px;color:#e8eaed;text-decoration:none;font-size:15px}}
.prods a i{{display:block;font-style:normal;color:#9aa0a6;font-size:12px;margin-top:3px}}
.note{{color:#9aa0a6;font-size:13px;line-height:1.8;margin-top:24px}}
a{{color:#8ab4f8}}
</style></head><body><div class="wrap">
<h1>一幕播单</h1>
<p class="sub">这里是自动维护的公开免费直播频道订阅地址。复制任意一条，粘贴到你的播放器订阅里就能看，地址长期不变，上游拉取失败时沿用已有缓存。</p>
<div class="stats">当前共 <b>{n_all}</b> 个频道 · 最近更新 {report.get("generated_at","")} · 每 6 小时尝试更新 · 播放可用性以播放器为准</div>
{cards}
{epg_card}
{products}
<p class="note">使用方法：在播放器里找到「订阅 / 播放列表 / M3U」入口，新建订阅，把上面的地址粘贴进去即可。适用于任何支持 M3U 的播放器（一幕 YiMu、VLC、TiviMate 等）。<br>
本站只收录互联网上公开免费的频道流并标注来源聚合，版权归各频道方所有；如有侵权请通过公众号「小产品实验室」联系删除。<br>
由小产品实验室维护。</p>
</div>
<script>
document.querySelectorAll("button[data-copy]").forEach(function(b){{
  if (!b.classList.contains("copy-name")) {{
    var file=b.getAttribute("data-copy").split("/").pop();
    var url=new URL(file, window.location.href).href;
    if (window.location.protocol === "https:") {{
      b.setAttribute("data-copy", url);
      b.previousElementSibling.textContent=url;
    }}
  }}
  b.addEventListener("click", function(){{
    navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function(){{
      var t=b.textContent; b.textContent="已复制"; b.classList.add("ok");
      setTimeout(function(){{b.textContent=t; b.classList.remove("ok");}},1500);
    }});
  }});
}});
</script></body></html>'''
    (SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"站点已生成：{SITE}（全量 {n_all} 条，EPG {'有' if has_epg else '无'}）")

if __name__ == "__main__":
    main()

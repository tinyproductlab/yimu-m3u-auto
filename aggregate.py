#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一幕 YiMu · 个人订阅聚合器 v1
流水线：拉取多路 M3U 源 -> 解析 -> 按 tvg-id/台名去重（优先级源优先，同源偏好 https）
-> 并发验活 -> 输出 merged.m3u；同时按各源声明的 x-tvg-url 合并 XMLTV -> epg.xml。
源拉取失败时自动回退上一版缓存，单源挂掉不会把整份清单打没。
只用 Python 标准库。用法：python3 aggregate.py [--no-check] [--timeout 6] [--workers 48]
"""
import argparse, gzip, io, json, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 YiMuAggregator/1.0"}

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')

def parse_m3u(text):
    """返回 (header_epg_urls, [entry,...])，entry 为 dict。"""
    entries, epg_urls, cur = [], [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            m = re.search(r'x-tvg-url="([^"]+)"', line)
            if m:
                epg_urls = [u.strip() for u in m.group(1).split(",") if u.strip()]
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            name = line.rsplit(",", 1)[-1].strip()
            tvg_id = attrs.get("tvg-id", "").strip() or attrs.get("tvg-name", "").strip()
            cur = {
                "tvg_id": tvg_id,
                "tvg_name": attrs.get("tvg-name", "").strip(),
                "logo": attrs.get("tvg-logo", "").strip(),
                "group": (attrs.get("group-title", "") or "未分组").strip(),
                "name": name,
            }
            continue
        if line.startswith("#"):
            continue
        if cur is not None:
            cur["url"] = line
            entries.append(cur)
            cur = None
    return epg_urls, entries

def norm_name(s):
    s = s.lower()
    s = re.sub(r"[\s\-_·•「」『』\[\]()（）]", "", s)
    s = re.sub(r"(hd|fhd|uhd|4k|8k|sd|高清|超清|蓝光)+$", "", s)
    return s

def dedupe(entries):
    """entries 已按源优先级排序；同键保留先出现者，但同键后来的 https 可顶替 http。"""
    best, order = {}, []
    for e in entries:
        key = (e["tvg_id"] or norm_name(e["tvg_name"] or e["name"]), norm_name(e["name"]))
        if key not in best:
            best[key] = e
            order.append(key)
        else:
            old = best[key]
            if old["url"].startswith("http://") and e["url"].startswith("https://") and old["source"] == e["source"]:
                best[key] = e
    return [best[k] for k in order]

def check_one(url, timeout):
    try:
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-4095"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status not in (200, 206):
                return False
            data = r.read(4096)
            if not data:
                return False
            if ".m3u8" in url:
                return b"#EXTM3U" in data or b"#EXTINF" in data or len(data) > 16
            return True
    except Exception:
        return False

def merge_epg(epg_urls, entries, out_path):
    """按保留频道的候选 id（tvg-id、去 @ 后缀、tvg-name、台名，含小写）合并多份 XMLTV，
    并把命中频道的 id 改写为清单里实际使用的 tvg-id，保证播放器能对上。返回 (频道数, 节目数)。"""
    cand2canon = {}
    for e in entries:
        canon = e["tvg_id"]
        if not canon:
            continue
        cands = {canon, canon.split("@")[0], e["tvg_name"], e["name"]}
        for c in cands:
            if c:
                cand2canon[c] = canon
                cand2canon[c.lower()] = canon
    chans, progs, seen_prog = {}, [], set()
    for url in epg_urls:
        try:
            data = fetch(url, timeout=60)
            root = ET.fromstring(data)
        except Exception as ex:
            print(f"  [epg] 拉取失败 {url}: {ex}")
            continue
        for ch in root.iter("channel"):
            cid = ch.get("id")
            canon = cand2canon.get(cid) or cand2canon.get((cid or "").lower())
            if canon and canon not in chans:
                ch.set("id", canon)
                chans[canon] = ch
        for pr in root.iter("programme"):
            cid = pr.get("channel")
            canon = cand2canon.get(cid) or cand2canon.get((cid or "").lower())
            sig = (canon, pr.get("start"), pr.get("stop"))
            if canon and sig not in seen_prog:
                seen_prog.add(sig)
                pr.set("channel", canon)
                progs.append(pr)
    if not chans:
        return 0, 0
    tv = ET.Element("tv", {"generator-info-name": "YiMuAggregator"})
    for ch in chans.values():
        tv.append(ch)
    for pr in progs:
        tv.append(pr)
    ET.ElementTree(tv).write(str(out_path), encoding="utf-8", xml_declaration=True)
    return len(chans), len(progs)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true", help="跳过验活")
    ap.add_argument("--timeout", type=float, default=6.0)
    ap.add_argument("--workers", type=int, default=48)
    args = ap.parse_args()

    sources = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
    sources.sort(key=lambda s: s["priority"])
    (BASE / "cache").mkdir(exist_ok=True)
    (BASE / "out").mkdir(exist_ok=True)

    all_entries, epg_urls_all, report = [], [], {"sources": {}, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    for src in sources:
        cache_file = BASE / "cache" / (src["name"] + ".m3u")
        degraded = False
        try:
            text = fetch(src["url"], timeout=40).decode("utf-8", "replace")
            epg_urls, entries = parse_m3u(text)
            if not text.lstrip("\ufeff \t\r\n").startswith("#EXTM3U") or not entries:
                raise ValueError("源未返回有效的频道清单")
            pending = cache_file.with_suffix(".tmp")
            pending.write_text(text, encoding="utf-8")
            pending.replace(cache_file)
        except Exception as ex:
            if cache_file.exists():
                text = cache_file.read_text(encoding="utf-8")
                epg_urls, entries = parse_m3u(text)
                degraded = True
                print(f"[{src['name']}] 拉取失败，回退缓存：{ex}")
            else:
                print(f"[{src['name']}] 拉取失败且无缓存，跳过：{ex}")
                report["sources"][src["name"]] = {"error": str(ex)}
                continue
        excl_g = src.get("exclude_group_keywords", [])
        excl_n = src.get("exclude_name_keywords", [])
        if excl_g or excl_n:
            before = len(entries)
            entries = [e for e in entries
                       if not any(k in e["group"] for k in excl_g)
                       and not any(k in e["name"] for k in excl_n)]
            print(f"[{src['name']}] 按源配置剔除 {before - len(entries)} 条（非直播/提示类）")
        for e in entries:
            e["source"] = src["name"]
        all_entries.extend(entries)
        for u in epg_urls + list(src.get("epg", [])):
            if u not in epg_urls_all:
                epg_urls_all.append(u)
        report["sources"][src["name"]] = {"fetched": len(entries), "degraded_cache": degraded}
        print(f"[{src['name']}] 解析 {len(entries)} 条，EPG 声明 {len(epg_urls)} 个")

    if not all_entries:
        sys.exit("没有可用频道，停止构建并保留上一版站点")

    merged = dedupe(all_entries)
    print(f"去重后 {len(merged)} 条（原始 {len(all_entries)} 条）")

    alive = merged
    if not args.no_check:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda e: check_one(e["url"], args.timeout), merged))
        alive = [e for e, ok in zip(merged, results) if ok]
        dead = len(merged) - len(alive)
        print(f"验活完成：存活 {len(alive)}，剔除 {dead}，耗时 {time.time()-t0:.0f}s")
        report["after_check"] = {"alive": len(alive), "dead": dead}
        if not alive and merged:
            print("警告：验活全灭，保留未验活清单兜底输出")
            alive = merged
    report["deduped"] = len(merged)
    report["final"] = len(alive)

    alive.sort(key=lambda e: (e["group"], e["name"]))
    out_m3u = BASE / "out" / "merged.m3u"
    lines = ["#EXTM3U"]
    body = []
    for e in alive:
        attrs = []
        if e["tvg_id"]:
            attrs.append(f'tvg-id="{e["tvg_id"]}"')
        if e["tvg_name"]:
            attrs.append(f'tvg-name="{e["tvg_name"]}"')
        if e["logo"]:
            attrs.append(f'tvg-logo="{e["logo"]}"')
        attrs.append(f'group-title="{e["group"]}"')
        body.append(f'#EXTINF:-1 {" ".join(attrs)},{e["name"]}')
        body.append(e["url"])
    out_m3u.write_text("\n".join(lines + body) + "\n", encoding="utf-8")

    nch = npr = 0
    if epg_urls_all and alive:
        nch, npr = merge_epg(epg_urls_all, alive, BASE / "out" / "epg.xml")
        print(f"EPG 合并：{nch} 个频道，{npr} 条节目")
        if nch:
            # 把 epg 引用写回 m3u 头（相对文件名，部署时与 merged.m3u 同目录）
            txt = out_m3u.read_text(encoding="utf-8")
            txt = txt.replace("#EXTM3U", '#EXTM3U x-tvg-url="epg.xml"', 1)
            out_m3u.write_text(txt, encoding="utf-8")
    report["epg"] = {"channels": nch, "programmes": npr}
    (BASE / "out" / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：out/merged.m3u 共 {len(alive)} 条频道")

if __name__ == "__main__":
    main()

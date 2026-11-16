"""위키미디어 공용(Wikimedia Commons)에서 자유 라이선스 예시 사진 후보를 내려받는다.

표준 라이브러리만 쓰므로 어떤 Python 3.9+에서도 바로 실행된다.
  py -3.12 tools\\fetch_stimuli.py            → stimuli/candidates/ 에 후보 사진 + candidates.json
다음 단계(크기·밝기 통일, manifest 생성)는 tools/build_stimuli.py 가 한다.

라이선스: CC0, Public domain, CC BY, CC BY-SA 만 받는다. 작가·라이선스·원본 링크를 함께 기록한다.
'Quality images' 범주(공용 커뮤니티가 품질 검토한 사진)에서만 찾는다.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "EEG-WebApp-stimuli/0.1 (research prototype; Python urllib)"
OUT = Path(__file__).resolve().parent.parent / "stimuli" / "candidates"
PER_CATEGORY = 14
QUERIES = {
    "nature": ["mountain lake landscape", "forest path autumn", "sea coast beach", "waterfall", "meadow flowers field", "snowy mountains"],
    "city": ["city skyline", "street night city", "old town square", "skyscrapers downtown", "harbour city", "bridge city river"],
    "animal": ["cat", "dog portrait", "fox", "deer", "owl", "squirrel", "horse"],
    "food": ["dish food plate", "cake dessert", "fruit", "bread bakery", "soup bowl", "pizza", "salad"],
}
OK_LICENSE = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? [0-9.]+)", re.I)


def api(params):
    url = API + "?" + urllib.parse.urlencode({"format": "json", **params})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def search(query, limit=20):
    data = api({"action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": limit,
                "gsrsearch": f"{query} incategory:Quality_images filemime:image/jpeg",
                "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1280})
    return list((data.get("query") or {}).get("pages", {}).values())


def acceptable(page):
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {})
    lic = strip_html(meta.get("LicenseShortName", {}).get("value"))
    w, h = info.get("width", 0), info.get("height", 0)
    if not OK_LICENSE.match(lic) or not w or not h:
        return None
    if not 1.2 <= w / h <= 1.8 or w < 1280:  # 가로 사진만 (4:3 근처)
        return None
    return {"title": page["title"], "license": lic,
            "license_url": meta.get("LicenseUrl", {}).get("value", ""),
            "artist": strip_html(meta.get("Artist", {}).get("value"))[:120] or "unknown",
            "source": info.get("descriptionurl"), "thumb": info.get("thumburl"),
            "description": strip_html(meta.get("ImageDescription", {}).get("value"))[:200]}


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        path.write_bytes(r.read())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    found = []
    for category, queries in QUERIES.items():
        chosen, seen = [], set()
        for q in queries:
            if len(chosen) >= PER_CATEGORY:
                break
            try:
                pages = search(q)
            except Exception as exc:
                print(f"  ! search failed '{q}': {exc}", file=sys.stderr)
                continue
            # 한 검색어에서 최대 3장만 → 다양성 확보
            taken = 0
            for p in sorted(pages, key=lambda p: p.get("index", 0)):
                c = acceptable(p)
                if not c or c["title"] in seen or taken >= 3 or len(chosen) >= PER_CATEGORY:
                    continue
                seen.add(c["title"])
                cid = f"{category}_c{len(chosen)+1:02d}"
                path = OUT / f"{cid}.jpg"
                try:
                    download(c["thumb"], path)
                except Exception as exc:
                    print(f"  ! download failed {c['title']}: {exc}", file=sys.stderr)
                    continue
                chosen.append({"candidate_id": cid, "category": category, "query": q, "file": path.name, **c})
                taken += 1
                time.sleep(0.3)
        print(f"{category}: {len(chosen)} candidates")
        found += chosen
    (OUT / "candidates.json").write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total {len(found)} -> {OUT}")


if __name__ == "__main__":
    main()

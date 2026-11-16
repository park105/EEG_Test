"""후보 사진(stimuli/candidates)에서 고른 사진으로 실험 자극 세트를 만든다. Pillow 필요(pip install pillow).

  python tools/build_stimuli.py --pick nature_c01 nature_c03 ... city_c02 ...

하는 일
- 가운데를 4:3으로 잘라 1024×768로 통일
- 밝기(휘도 평균·대비)를 모든 사진에서 같게 맞춤 → 밝기 차이가 EEG에 섞이는 것을 줄임
- 평균 색(R−B)으로 따뜻한/차가운 색감(tone)을 자동 분류
- stimuli/images/<category>_<nn>.jpg, stimuli/manifest.json, stimuli/CREDITS.md 생성
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "stimuli"
KOREAN = {"nature": "자연", "city": "도시", "animal": "동물", "food": "음식"}
SIZE = (1024, 768)
TARGET_MEAN, TARGET_SD = 118.0, 52.0  # 휘도(Y) 목표 평균·표준편차


def crop_43(img):
    w, h = img.size
    if w / h > 4 / 3:
        nw = int(h * 4 / 3)
        return img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    nh = int(w * 3 / 4)
    return img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))


def equalize_luminance(img):
    ycc = np.asarray(img.convert("YCbCr"), dtype=float)
    y = ycc[..., 0]
    ycc[..., 0] = np.clip((y - y.mean()) / (y.std() + 1e-6) * TARGET_SD + TARGET_MEAN, 0, 255)
    return Image.fromarray(ycc.astype(np.uint8), "YCbCr").convert("RGB")


def tone_of(img):
    a = np.asarray(img, dtype=float)
    score = float(a[..., 0].mean() - a[..., 2].mean())
    return ("warm" if score >= 0 else "cool"), round(score, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", nargs="+", required=True, help="candidate_id 목록 (candidates.json 참고)")
    args = ap.parse_args()
    cands = {c["candidate_id"]: c for c in json.loads((ROOT / "candidates" / "candidates.json").read_text(encoding="utf-8"))}
    missing = [p for p in args.pick if p not in cands]
    if missing:
        raise SystemExit(f"없는 후보: {missing}")
    (ROOT / "images").mkdir(exist_ok=True)
    counters, stimuli = {}, []
    for pid in args.pick:
        c = cands[pid]
        cat = c["category"]
        counters[cat] = counters.get(cat, 0) + 1
        sid = f"{cat}_{counters[cat]:02d}"
        img = Image.open(ROOT / "candidates" / c["file"]).convert("RGB")
        img = equalize_luminance(crop_43(img).resize(SIZE, Image.LANCZOS))
        tone, score = tone_of(img)
        img.save(ROOT / "images" / f"{sid}.jpg", quality=90)
        stimuli.append({"id": sid, "type": "image", "src": f"/stimuli/images/{sid}.jpg",
                        "title": f"{KOREAN[cat]} {counters[cat]}", "category": cat, "tone": tone,
                        "tone_score": score,
                        "credit": {k: c[k] for k in ("title", "artist", "license", "license_url", "source")}})
    manifest = {"note": "위키미디어 공용의 자유 라이선스 사진(예시). 1024×768, 휘도 평균·대비 통일. "
                        "tone은 평균 R−B로 자동 분류. 출처는 CREDITS.md.",
                "stimuli": stimuli}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 자극 사진 출처", "",
             "모든 사진은 위키미디어 공용(Wikimedia Commons)의 자유 라이선스 사진입니다. "
             "실험용으로 4:3으로 자르고 1024×768로 줄였으며 밝기(휘도)를 조정했습니다.", "",
             "| 자극 | 원본 | 작가 | 라이선스 |", "|---|---|---|---|"]
    for s in stimuli:
        cr = s["credit"]
        lic = f"[{cr['license']}]({cr['license_url']})" if cr["license_url"] else cr["license"]
        lines.append(f"| {s['id']} | [{cr['title'].replace('File:', '')}]({cr['source']}) | {cr['artist'].replace('|', '/')} | {lic} |")
    (ROOT / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(stimuli)} stimuli: " + ", ".join(f"{k} {v}" for k, v in counters.items()))
    tones = [s["tone"] for s in stimuli]
    print(f"tone: warm {tones.count('warm')}, cool {tones.count('cool')}")


if __name__ == "__main__":
    main()

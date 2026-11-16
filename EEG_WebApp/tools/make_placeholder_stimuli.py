"""시연용 자리표시 이미지(SVG) 12장과 manifest.json을 stimuli/placeholder/에 만든다.
(실제 예시 사진 세트는 tools/fetch_stimuli.py → tools/build_stimuli.py로 만든다.)
자리표시 세트로 돌리려면 stimuli/placeholder/manifest.json을 stimuli/manifest.json으로 복사.

실제 실험에서는 stimuli/images/에 동의·라이선스를 확인한 이미지를 넣고
manifest.json의 category / tone을 채우면 된다. 밝기·크기는 미리 통일할 것.
실행:  python tools/make_placeholder_stimuli.py
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "stimuli" / "placeholder"
CATEGORIES = {"nature": "자연", "city": "도시", "animal": "동물", "food": "음식"}
PALETTES = {"warm": ["#f4a261", "#e76f51", "#f2cc8f", "#e9c46a"],
            "cool": ["#457b9d", "#a8dadc", "#2a9d8f", "#8ecae6"]}


def scene(category: str, tone: str, rng: random.Random) -> str:
    bg, a, b, c = rng.sample(PALETTES[tone], 4)
    w, h = 800, 600
    shapes = []
    if category == "nature":
        shapes.append(f'<circle cx="{rng.randint(550, 700)}" cy="140" r="60" fill="{c}"/>')
        for x in range(-100, 900, 260):
            peak = rng.randint(180, 300)
            shapes.append(f'<polygon points="{x},600 {x+220},{peak} {x+440},600" fill="{a}" opacity="0.9"/>')
        shapes.append(f'<rect x="0" y="480" width="800" height="120" fill="{b}"/>')
    elif category == "city":
        x = 20
        while x < 780:
            bw, bh = rng.randint(60, 120), rng.randint(180, 460)
            shapes.append(f'<rect x="{x}" y="{600-bh}" width="{bw}" height="{bh}" fill="{rng.choice([a, b])}"/>')
            for wy in range(600 - bh + 20, 580, 40):
                for wx in range(x + 12, x + bw - 16, 26):
                    shapes.append(f'<rect x="{wx}" y="{wy}" width="12" height="18" fill="{c}" opacity="0.8"/>')
            x += bw + rng.randint(8, 20)
    elif category == "animal":
        cx, cy = 400, 330
        shapes += [f'<circle cx="{cx-120}" cy="{cy-130}" r="60" fill="{a}"/>',
                   f'<circle cx="{cx+120}" cy="{cy-130}" r="60" fill="{a}"/>',
                   f'<circle cx="{cx}" cy="{cy}" r="180" fill="{a}"/>',
                   f'<circle cx="{cx-60}" cy="{cy-30}" r="18" fill="#222"/>',
                   f'<circle cx="{cx+60}" cy="{cy-30}" r="18" fill="#222"/>',
                   f'<ellipse cx="{cx}" cy="{cy+50}" rx="40" ry="28" fill="{c}"/>']
    else:  # food
        shapes += [f'<ellipse cx="400" cy="380" rx="300" ry="90" fill="{a}"/>',
                   f'<path d="M120,370 Q400,620 680,370 Z" fill="{b}"/>']
        for _ in range(9):
            shapes.append(f'<circle cx="{rng.randint(200, 600)}" cy="{rng.randint(320, 380)}" r="{rng.randint(25, 45)}" fill="{c}"/>')
    label = f'<text x="20" y="585" font-family="sans-serif" font-size="18" fill="#000" opacity="0.35">샘플 자극 · {CATEGORIES[category]}</text>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<rect width="{w}" height="{h}" fill="{bg}"/>{"".join(shapes)}{label}</svg>')


def main():
    rng = random.Random(2026)
    (ROOT / "images").mkdir(parents=True, exist_ok=True)
    stimuli = []
    tones = ["warm", "cool", "warm"]
    for category, korean in CATEGORIES.items():
        for i in range(3):
            tone = tones[i] if category in {"nature", "animal"} else tones[(i + 1) % 3]
            sid = f"{category}_{i+1:02d}"
            (ROOT / "images" / f"{sid}.svg").write_text(scene(category, tone, rng), encoding="utf-8")
            stimuli.append({"id": sid, "type": "image", "src": f"/stimuli/placeholder/images/{sid}.svg",
                            "title": f"{korean} {i+1}", "category": category, "tone": tone})
    manifest = {"note": "자리표시 자극입니다. 실제 이미지로 바꾸고 category/tone을 설문 문항과 맞추세요. "
                        "type: video는 확장 예정(README 참고).",
                "stimuli": stimuli}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(stimuli)} stimuli -> {ROOT}")


if __name__ == "__main__":
    main()

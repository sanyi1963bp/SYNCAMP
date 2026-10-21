"""A szerkeszthető feliratok és a saját MilkDrop-látványok előállítása.

Képek (milkdrop/textures/):
  syncamp_logo.png  – a felirat (hosszú szöveg magától több sorba tördelődik)
  syncamp_intro.png – a "Réges-régen…" bevezető sor
  syncamp_crawl.png – a csillagháborús futó szöveg (cím + bekezdések)
Látványok:
  presets/! SYNCAMP/*.milk – feliratos látványok (a véletlen váltásban is szerepelnek)
  special/SYNCAMP - Csillagok.milk – a futó szöveg (csak gombra indul)

Minden látvány három részből áll:
  per_frame – képkockánként egyszer fut, a zenéből (bass/mid/treb) számolja a
              mozgást, és q1..q8 változókban átadja a shadereknek;
  warp      – az előző képet viszi tovább (nyomvonal, örvény) és ráfesti a feliratot;
  comp      – a végső kép: fényglória + éles felirat felül.
"""

import html
import os

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QPainter, QPainterPath,
                           QPen, QTextDocument)

HERE = os.path.dirname(os.path.abspath(__file__))
MD_DIR = os.path.join(HERE, "milkdrop")
OUT = os.path.join(MD_DIR, "presets", "! SYNCAMP")
SPECIAL_DIR = os.path.join(MD_DIR, "special")
CRAWL_PRESET = os.path.join(SPECIAL_DIR, "SYNCAMP - Csillagok.milk")
TEX_DIR = os.path.join(MD_DIR, "textures")
LOGO_PNG = os.path.join(TEX_DIR, "syncamp_logo.png")
INTRO_PNG = os.path.join(TEX_DIR, "syncamp_intro.png")
CRAWL_PNG = os.path.join(TEX_DIR, "syncamp_crawl.png")

DEFAULT_TEXTS = {
    "logo": "SYNCAMP",
    "intro": "Réges-régen, egy messzi-messzi\ngalaxisban…",
    "subtitle": "I. RÉSZ",
    "title": "A SZINKRON EREJE",
    "crawl": (
        "Sötét idők járnak. A zenelejátszók látványai mind késnek: "
        "a dob már rég elhallgatott, mire a kép megmozdul.\n\n"
        "Egy maroknyi lázadó azonban titkos fegyvert épített. A SYNCAMP "
        "előre feldolgoz minden hangot, és a képet pontosan a hangszóró "
        "órájához igazítja.\n\n"
        "Most, hogy a dobütés és a fény végre egy pillanatban születik, "
        "a galaxis minden táncparkettje új reményt kap…"
    ),
    "speed": "közepes",
}
SPEEDS = {"lassú": 0.032, "közepes": 0.045, "gyors": 0.07}

# q1 = szög, q2/q3 = x/y méret, q4/q5 = x/y eltolás, q6 = színfázis,
# q7 = pumpa (0..1), q8 = billenés (3D)
#
# A projectM shader-fordítója nem ismeri a saját függvényeket, ezért a felirat
# kiszámítása minden használatnál beíródik a kódba. A shaderekben egy
#   @LOGO név | pont | szög | x-méret | y-méret | billenés
# sor jelöli, hová kerüljön; utána `név` (float3) a felirat színe az adott pontban.
SAMPLER = "sampler sampler_fc_syncamp_logo;"


def logo_code(v, p, ang, sx, sy, tilt):
    return f"""
    float2 {v}_p = {p};
    float {v}_c = cos({ang});
    float {v}_s = sin({ang});
    {v}_p = float2({v}_c*{v}_p.x + {v}_s*{v}_p.y, -{v}_s*{v}_p.x + {v}_c*{v}_p.y);
    {v}_p.y = {v}_p.y / max(0.15, cos({tilt}));
    {v}_p = {v}_p / (1.0 + {v}_p.y*sin({tilt})*0.9);
    {v}_p = {v}_p / float2({sx}, {sy});
    float2 {v}_uv = {v}_p / float2(0.9, 0.225) + 0.5;
    float3 {v} = tex2D(sampler_fc_syncamp_logo, {v}_uv).xyz;"""


def hue(h):
    return f"(0.55 + 0.45*cos(6.2832*(({h}) + float3(0.0, 0.33, 0.67))))"


# a felirat a képernyő-középhez viszonyítva, oldalarány-helyesen
P_WARP = "float2 p = uv_orig - 0.5;\n    p.x *= texsize.x*texsize.w;"
P_COMP = "float2 p = uv - 0.5;\n    p.x *= texsize.x*texsize.w;"
LOGO = "@LOGO lg | p - float2(q4, q5) | q1 | q2 | q3 | q8"

BASE = {
    "fRating": "5.000", "fGammaAdj": "1.000", "fDecay": "0.980",
    "fVideoEchoZoom": "1.000", "fVideoEchoAlpha": "0.000", "nVideoEchoOrientation": "0",
    "nWaveMode": "6", "bAdditiveWaves": "1", "bWaveDots": "0", "bWaveThick": "1",
    "bModWaveAlphaByVolume": "0", "bMaximizeWaveColor": "1", "bTexWrap": "0",
    "bDarkenCenter": "0", "bRedBlueStereo": "0", "bBrighten": "0", "bDarken": "0",
    "bSolarize": "0", "bInvert": "0", "fWaveAlpha": "0.000", "fWaveScale": "1.000",
    "fWaveSmoothing": "0.600", "fWaveParam": "0.000", "fModWaveAlphaStart": "0.750",
    "fModWaveAlphaEnd": "0.950", "fWarpAnimSpeed": "1.000", "fWarpScale": "1.000",
    "fZoomExponent": "1.000", "fShader": "0.000", "zoom": "1.000", "rot": "0.000",
    "cx": "0.500", "cy": "0.500", "dx": "0.000", "dy": "0.000", "warp": "0.000",
    "sx": "1.000", "sy": "1.000", "wave_r": "1.000", "wave_g": "1.000", "wave_b": "1.000",
    "wave_x": "0.500", "wave_y": "0.500", "ob_size": "0.000", "ob_a": "0.000",
    "ib_size": "0.000", "ib_a": "0.000", "nMotionVectorsX": "0.000",
    "nMotionVectorsY": "0.000", "mv_a": "0.000",
    "b1n": "0.000", "b2n": "0.000", "b3n": "0.000", "b1x": "1.000", "b2x": "1.000",
    "b3x": "1.000", "b1ed": "0.250",
}

# közös zenei előkészítés: dt, pumpa (dobütésre ugrik, aztán lecseng)
COMMON_FRAME = """
dt = min(time - lt, 0.1);
lt = time;
pump = max(pump*0.86, min(1, max(bass - 1.0, 0)*1.4));
q7 = pump;
q8 = 0;
q4 = 0;
q5 = 0;
"""

PRESETS = {
    "Pumpálás": dict(
        params={"fDecay": "0.960"},
        frame="""
spin = spin + dt*(0.4 + 1.6*max(mid_att - 1, 0));
q1 = 0.22*sin(spin);
q2 = 0.55 + 0.6*pump;
q3 = q2;
q6 = time*0.04 + pump*0.3;
zoom = 1.015 + 0.05*pump;
rot = 0;
""",
        warp=f"""
    ret = tex2D(sampler_main, uv).xyz*0.93 - 0.004;
    {P_WARP}
    {LOGO}
    ret = max(ret, lg*{hue("q6")});
""",
        comp=f"""
    {P_COMP}
    {LOGO}
    ret = tex2D(sampler_main, uv).xyz;
    ret += GetBlur1(uv)*(0.35 + 0.5*q7);
    ret += lg*(0.75 + 0.25*q7);
""",
    ),
    "Forgószél": dict(
        params={"fDecay": "0.970"},
        frame="""
spin = spin + dt*(1.2 + 4.0*max(bass_att - 0.9, 0));
q1 = spin;
q2 = 0.42 + 0.18*min(bass_att, 2);
q3 = q2;
q6 = spin*0.05;
zoom = 0.965 - 0.03*pump;
rot = 0.04 + 0.06*pump;
""",
        warp=f"""
    ret = tex2D(sampler_main, uv).xyz*0.95 - 0.003;
    {P_WARP}
    {LOGO}
    ret = max(ret, lg*{hue("q6 + length(p)")});
""",
        comp=f"""
    {P_COMP}
    {LOGO}
    ret = tex2D(sampler_main, uv).xyz + GetBlur1(uv)*0.5;
    ret += lg*0.6;
""",
    ),
    "Pattogás": dict(
        params={"fDecay": "0.950", "nWaveMode": "2", "fWaveAlpha": "0.700", "fWaveScale": "1.400"},
        frame="""
t1 = t1 + dt*(0.8 + 1.5*mid_att);
t2 = t2 + dt*(1.6 + 2.0*bass_att);
q4 = 0.42*sin(t1*0.9);
q5 = 0.30*abs(sin(t2)) - 0.12;
kick = max(kick*0.9, pump);
q1 = 0.35*sin(time*1.3)*kick + 0.12*sin(t1*2);
q8 = 1.1*sin(t1*1.7)*kick;
q2 = 0.38 + 0.25*pump;
q3 = q2;
q6 = time*0.07;
wave_r = 0.5 + 0.5*sin(time*1.1);
wave_g = 0.5 + 0.5*sin(time*1.3 + 2);
wave_b = 0.5 + 0.5*sin(time*1.7 + 4);
zoom = 1.0;
rot = 0;
""",
        warp=f"""
    ret = tex2D(sampler_main, uv).xyz*0.90 - 0.006;
    {P_WARP}
    {LOGO}
    ret = max(ret, lg*{hue("q6")}*0.9);
""",
        comp=f"""
    {P_COMP}
    {LOGO}
    ret = tex2D(sampler_main, uv).xyz + GetBlur1(uv)*0.4;
    ret += lg;
""",
    ),
    "Kaleidoszkóp": dict(
        params={"fDecay": "0.970"},
        frame="""
spin = spin + dt*(0.3 + 1.2*max(treb_att - 0.9, 0));
q1 = spin;
q2 = 0.30 + 0.12*pump;
q3 = q2;
q4 = 0.33 + 0.12*pump;
q6 = time*0.05;
zoom = 1.0 + 0.03*pump;
rot = 0.02;
""",
        # hat feliratból álló csillag; nem tükrözünk, csak forgatva ismételünk,
        # így mindegyik felirat olvasható marad
        warp=f"""
    ret = tex2D(sampler_main, uv).xyz*0.94 - 0.004;
    {P_WARP}
    float r = length(p);
    float a = atan2(p.y, p.x) + q1;
    float seg = 6.2832/6.0;
    a = fmod(a + seg*60.5, seg) - seg*0.5;
    float2 k = r*float2(cos(a), sin(a));
    @LOGO star | k - float2(q4, 0.0) | 1.5708 | q2 | q3 | 0.0
    ret = max(ret, star*{hue("q6 + r*1.5")}*0.8);
""",
        comp=f"""
    {P_COMP}
    float r = length(p);
    float a = atan2(p.y, p.x) + q1;
    float seg = 6.2832/6.0;
    a = fmod(a + seg*60.5, seg) - seg*0.5;
    float2 k = r*float2(cos(a), sin(a));
    @LOGO star | k - float2(q4, 0.0) | 1.5708 | q2 | q3 | 0.0
    ret = tex2D(sampler_main, uv).xyz*0.85 + GetBlur1(uv)*0.6;
    ret += star*{hue("q6 + r*1.5 + 0.5")};
""",
    ),
    "Gumi": dict(
        params={"fDecay": "0.960"},
        frame="""
squash = squash*0.8 + pump*0.2;
q1 = 0.1*sin(time*0.8);
q2 = 0.55*(1 + 0.45*squash);
q3 = 0.55*(1 - 0.35*squash);
q6 = time*0.03;
q8 = 0.25*sin(time*0.6);
zoom = 1.01;
rot = 0;
""",
        warp=f"""
    ret = tex2D(sampler_main, uv).xyz*0.92 - 0.005;
    {P_WARP}
    p.y += 0.035*sin(p.x*14.0 + time*6.0)*treb_att;
    p.x += 0.02*sin(p.y*20.0 + time*4.0)*mid_att;
    {LOGO}
    ret = max(ret, lg*{hue("q6 + p.x*0.4")});
""",
        comp=f"""
    {P_COMP}
    p.y += 0.035*sin(p.x*14.0 + time*6.0)*treb_att;
    p.x += 0.02*sin(p.y*20.0 + time*4.0)*mid_att;
    {LOGO}
    ret = tex2D(sampler_main, uv).xyz + GetBlur1(uv)*(0.3 + 0.4*q7);
    ret += lg*0.85;
""",
    ),
}


def expand(body):
    out = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("@LOGO "):
            v, *args = [a.strip() for a in s[len("@LOGO "):].split("|")]
            out.append(logo_code(v, *args))
        else:
            out.append(ln)
    return "\n".join(out)


def shader_lines(prefix, body, header=""):
    if "@LOGO" in body:
        header = SAMPLER + "\n" + header
    code = header + "shader_body\n{" + expand(body) + "}\n"
    lines = [ln for ln in code.split("\n") if ln.strip() != ""]
    return [f"{prefix}_{i}=`{ln}" for i, ln in enumerate(lines, 1)]


def frame_lines(code, common=True):
    lines = [ln.strip() for ln in ((COMMON_FRAME if common else "") + code).split("\n") if ln.strip()]
    return [f"per_frame_{i}={ln}" for i, ln in enumerate(lines, 1)]


def build(spec, common=True, header=""):
    params = dict(BASE)
    params.update(spec["params"])
    out = ["MILKDROP_PRESET_VERSION=201", "PSVERSION=2", "PSVERSION_WARP=2",
           "PSVERSION_COMP=2", "[preset00]"]
    out += [f"{k}={v}" for k, v in params.items()]
    out += frame_lines(spec["frame"], common)
    out += shader_lines("warp", spec["warp"], header)
    out += shader_lines("comp", spec["comp"], header)
    return "\n".join(out) + "\n"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)


# --------------------------------------------------------------------------
# Csillagok háborúja: bevezető sor → zsugorodó cím → perspektivikus futó szöveg
# --------------------------------------------------------------------------
INTRO_START, INTRO_END = 0.5, 6.0     # mp
LOGO_START, LOGO_END = 7.0, 14.0
CRAWL_START = 8.5
HORIZON = 0.93       # ennél a képmagasságnál (alulról) tűnik el a szöveg
TEXT_W = 1.05        # a szöveg szélessége a kép alján, képmagasságban mérve
SCALE_T = 0.85 / TEXT_W
FADE = 3.5           # ennyi szövegszélességnyi távolság után halványul el


def build_crawl(crawl_ratio, intro_ratio, speed):
    total = CRAWL_START + (crawl_ratio + FADE) / speed + 3.0
    frame = f"""
st = if(above(st, 0), st, time);
t = time - st;
tt = t - {total:.3f}*int(t/{total:.3f});
q1 = max(0, tt - {CRAWL_START})*{speed};
q2 = min(1, max(0, min(tt - {INTRO_START}, {INTRO_END} - tt)));
q4 = 2.8*exp(-0.42*max(tt - {LOGO_START}, 0));
q5 = above(tt, {LOGO_START})*min(1, max(0, {LOGO_END} - tt));
q6 = 0.65 + 0.35*min(bass_att, 1.5);
zoom = 1;
rot = 0;
"""
    header = ("sampler sampler_fc_syncamp_crawl;\n"
              "sampler sampler_fc_syncamp_intro;\n" + SAMPLER + "\n")
    comp = f"""
    float asp = texsize.x*texsize.w;
    float2 cell = floor(uv*texsize.xy*0.5);
    float h = frac(sin(dot(cell, float2(12.9898, 78.233)))*43758.5453);
    float tw = 0.55 + 0.45*sin(time*2.3 + h*60.0);
    ret = float3(1.0, 1.0, 1.0)*step(0.9972, h)*tw*q6;
    float2 ip = uv - 0.5;
    ip.x *= asp;
    float2 iu = ip/float2(1.3, 1.3*{intro_ratio:.4f}) + 0.5;
    ret += tex2D(sampler_fc_syncamp_intro, iu).xyz*float3(0.29, 0.75, 0.93)*q2;
    float2 lu = ip/float2(0.9*q4, 0.225*q4) + 0.5;
    ret += tex2D(sampler_fc_syncamp_logo, lu).xyz*float3(1.0, 0.91, 0.12)*q5;
    float y = 1.0 - uv.y;
    float v = {HORIZON}*{HORIZON}/max({HORIZON} - y, 0.0005);
    float tr = (v - {HORIZON})*{SCALE_T:.4f};
    float r = q1 - tr;
    float2 cu;
    cu.x = (uv.x - 0.5)*asp*(v/{HORIZON})/{TEXT_W} + 0.5;
    cu.y = r/{crawl_ratio:.4f};
    float inside = step(0.0, r)*step(r, {crawl_ratio:.4f})*step(y, {HORIZON});
    float fade = saturate(1.0 - tr/{FADE});
    ret += tex2D(sampler_fc_syncamp_crawl, cu).xyz*inside*fade;
"""
    spec = dict(params={"fDecay": "1.000"}, frame=frame,
                warp="\n    ret = float3(0.0, 0.0, 0.0);\n", comp=comp)
    return build(spec, common=False, header=header)


# --------------------------------------------------------------------------
# Képek
# --------------------------------------------------------------------------
def _family(*names):
    have = set(QFontDatabase.families())
    for n in names:
        if n in have:
            return n
    return "Arial"


def _wrap(words, k):
    """A szavakat k nagyjából egyforma hosszú sorba osztja."""
    total = sum(len(w) for w in words) + len(words) - 1
    target = total / k
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and len(cand) > target and len(lines) < k - 1:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    lines.append(cur)
    return lines


def render_logo(text, out=LOGO_PNG, W=2048, H=512):
    """Fehér felirat fekete alapon; a hosszú szöveg magától több sorba kerül."""
    text = text.strip() or " "
    font = QFont(_family("Arial Black", "Arial"))
    font.setBold(True)
    if "\n" in text:
        candidates = [[ln.strip() for ln in text.split("\n") if ln.strip()]]
    else:
        words = text.split()
        candidates = [_wrap(words, k) for k in range(1, min(6, len(words)) + 1)]

    def fit(lines):
        font.setPixelSize(100)
        widest = max(_path(font, ln).boundingRect().width() for ln in lines) or 1
        by_w = 100 * W * 0.94 / widest
        by_h = H * 0.86 / (len(lines) * 1.05)
        return min(by_w, by_h)

    lines = max(candidates, key=fit)
    size = max(8, int(fit(lines)))
    font.setPixelSize(size)
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(Qt.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    step = size * 1.05
    y0 = H / 2 - step * (len(lines) - 1) / 2
    paths = []
    for i, ln in enumerate(lines):
        path = _path(font, ln)
        r = path.boundingRect()
        path.translate(W / 2 - r.center().x(), y0 + i * step - r.center().y())
        paths.append(path)
    for width, shade in ((0.16, 40), (0.09, 90), (0.045, 170)):
        p.setPen(QPen(QColor(shade, shade, shade), max(1.0, size * width),
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for path in paths:
            p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    for path in paths:
        p.drawPath(path)
    p.end()
    img.save(out)


def _path(font, text):
    path = QPainterPath()
    path.addText(0, 0, font, text)
    return path


def render_intro(text, out=INTRO_PNG, W=2048, H=512):
    """A kék bevezető sor (fehéren rajzolva, a látvány színezi kékre). Arány: H/W."""
    lines = [ln for ln in (text or " ").split("\n")]
    font = QFont(_family("Franklin Gothic Book", "Segoe UI", "Arial"))
    size = 200
    while size > 10:
        font.setPixelSize(size)
        widest = max(_path(font, ln).boundingRect().width() for ln in lines)
        if widest <= W * 0.95 and len(lines) * size * 1.25 <= H * 0.95:
            break
        size -= 4
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(Qt.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(font)
    p.setPen(Qt.white)
    fm = p.fontMetrics()
    y = (H - len(lines) * size * 1.25) / 2 + fm.ascent()
    for ln in lines:
        p.drawText(int(W * 0.03), int(y), ln)
        y += size * 1.25
    p.end()
    img.save(out)
    return H / W


def render_crawl(subtitle, title, body, out=CRAWL_PNG, W=1024):
    """Sárga, sorkizárt futó szöveg. Visszaadja a kép magasság/szélesség arányát."""
    fam = _family("Franklin Gothic Medium", "Franklin Gothic Demi", "Arial")
    paras = [p.strip() for p in body.replace("\r", "").split("\n\n") if p.strip()]
    parts = []
    if subtitle.strip():
        parts.append(f'<p align="center" style="font-size:44px; margin:0">{html.escape(subtitle)}</p>')
    if title.strip():
        parts.append(f'<p align="center" style="font-size:78px; font-weight:bold; margin-top:6px; '
                     f'margin-bottom:46px">{html.escape(title)}</p>')
    for para in paras:
        txt = html.escape(para).replace("\n", "<br>")
        parts.append(f'<p align="justify" style="font-size:48px; margin-bottom:40px">{txt}</p>')
    doc = QTextDocument()
    doc.setDefaultFont(QFont(fam))
    doc.setDocumentMargin(0)
    doc.setDefaultStyleSheet("p { color: #FFE81F; }")
    doc.setHtml(f'<div style="font-family:\'{fam}\'; color:#FFE81F">{"".join(parts)}</div>')
    margin = 48
    doc.setTextWidth(W - 2 * margin)
    h = int(doc.size().height()) + 2 * margin
    h = min(h, 16000)
    img = QImage(W, h, QImage.Format_RGB32)
    img.fill(Qt.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.translate(margin, margin)
    doc.drawContents(p, QRectF(0, 0, W - 2 * margin, h - 2 * margin))
    p.end()
    img.save(out)
    return h / W


def generate_all(texts):
    """Minden kép és látvány újragenerálása a megadott szövegekből."""
    t = dict(DEFAULT_TEXTS)
    t.update({k: v for k, v in (texts or {}).items() if v is not None})
    os.makedirs(TEX_DIR, exist_ok=True)
    render_logo(t["logo"])
    intro_ratio = render_intro(t["intro"])
    crawl_ratio = render_crawl(t["subtitle"], t["title"], t["crawl"])
    for name, spec in PRESETS.items():
        _write(os.path.join(OUT, f"SYNCAMP - {name}.milk"), build(spec))
    speed = SPEEDS.get(t["speed"], SPEEDS["közepes"])
    _write(CRAWL_PRESET, build_crawl(crawl_ratio, intro_ratio, speed))


def ensure_generated(texts):
    own = [os.path.join(OUT, f"SYNCAMP - {name}.milk") for name in PRESETS]
    if not all(os.path.exists(p) for p in own + [LOGO_PNG, INTRO_PNG, CRAWL_PNG, CRAWL_PRESET]):
        generate_all(texts)


if __name__ == "__main__":
    import sys
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv)
    generate_all({})
    print("kész")

"""A MilkDrop-látványcsomag letöltése (egyszer kell, a setup.bat futtatja).

- projectM "Cream of the Crop" presetcsomag  -> milkdrop/presets/
- MilkDrop textúracsomag                     -> milkdrop/textures/
A SYNCAMP saját látványait és feliratképeit a program maga készíti el induláskor.
"""

import io
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MD = os.path.join(HERE, "milkdrop")
PACKS = [
    ("https://github.com/projectM-visualizer/presets-cream-of-the-crop/archive/refs/heads/master.zip",
     "presets-cream-of-the-crop-master/", os.path.join(MD, "presets")),
    ("https://github.com/projectM-visualizer/presets-milkdrop-texture-pack/archive/refs/heads/master.zip",
     "presets-milkdrop-texture-pack-master/textures/", os.path.join(MD, "textures")),
]


def fetch(url):
    print("Letöltés:", url)
    with urllib.request.urlopen(url) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            if total:
                print(f"\r  {buf.tell() * 100 // total:3d}%", end="", flush=True)
        print()
    return buf


def extract(buf, prefix, dest):
    n = 0
    with zipfile.ZipFile(buf) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix):]
            target = os.path.normpath(os.path.join(dest, rel))
            if not target.startswith(os.path.normpath(dest) + os.sep):
                continue    # biztonság: zipen kívülre mutató útvonal
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            n += 1
    return n


def main():
    for url, prefix, dest in PACKS:
        marker = os.path.join(dest, ".downloaded")
        if os.path.exists(marker):
            print("Már megvan:", dest)
            continue
        n = extract(fetch(url), prefix, dest)
        open(marker, "w").close()
        print(f"  {n} fájl -> {dest}")
    print("Kész. Indítás: Syncamp.bat")


if __name__ == "__main__":
    sys.exit(main())

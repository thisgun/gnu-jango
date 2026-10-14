"""Generate the shared Korean UI font from the pinned Pretendard 1.3.9 package.

Optional regeneration tooling: fonttools==4.66.1, brotli==1.2.0.
The generated asset is checked in; production builds do not need Python font tooling.
"""

from pathlib import Path
import json
import re

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2"
TARGET = ROOT / "src/assets/fonts/GnuUI.woff2"


def common_unicode():
    # Pretendard orders its dynamic subsets by frequency. Merge the twelve commonest
    # ranges without changing glyph coverage or shipping a large all-Korean font.
    stylesheet = SOURCE.parent.parent / "pretendardvariable-dynamic-subset.css"
    characters = set()
    for number, ranges in re.findall(r"/\* \[(\d+)\] \*/.*?unicode-range:\s*([^;]+)", stylesheet.read_text(encoding="utf-8"), re.S):
        if int(number) < 80:
            continue
        for value in ranges.split(","):
            bounds = value.strip().removeprefix("U+").split("-")
            characters.update(range(int(bounds[0], 16), int(bounds[-1], 16) + 1))
    return characters


def main():
    package = ROOT / "node_modules/pretendard/package.json"
    if json.loads(package.read_text(encoding="utf-8"))["version"] != "1.3.9":
        raise ValueError("Review the source ranges and license before changing Pretendard versions.")
    font = TTFont(SOURCE, recalcTimestamp=False)
    # The subset is a modified font: use a new family name and retain the original OFL notices.
    for entry in font["name"].names:
        if entry.nameID in (1, 3, 4, 6, 16, 21, 25):
            name = entry.toUnicode().replace("PretendardVariable", "GnuUI").replace("Pretendard", "Gnu UI")
            entry.string = name.encode(entry.getEncoding())
    options = subset.Options()
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.recalc_timestamp = False
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=common_unicode())
    subsetter.subset(font)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    font.flavor = "woff2"
    font.save(TARGET)
    print(f"{TARGET.name}: {TARGET.stat().st_size:,} bytes; {len(font.getBestCmap()):,} codepoints")


if __name__ == "__main__":
    main()

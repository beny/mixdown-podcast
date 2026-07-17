"""Doplní tracklisty a přepis úvodu k epizodám z mixdown.xml.

Projde feed, najde epizody bez uloženého tracklistu nebo přepisu, stáhne
jejich MP3, rozpozná skladby přes Shazam (tracklist.py) a přepíše mluvený
úvod přes Whisper (transcript.py). Výsledky uloží jako
tracklists/<číslo>.json a transcripts/<číslo>.txt. Je idempotentní — už
hotové epizody přeskakuje, takže se dá kdykoli přerušit a spustit znovu.

Použití:
    python enrich.py               # nejnovější 3 chybějící epizody
    python enrich.py --limit 10    # max 10 chybějících epizod
    python enrich.py --all         # všechny chybějící (backfill, běží hodiny)
"""

import argparse
import asyncio
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from tracklist import build_tracklist
from transcript import transcribe_intro

ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
XML_FILE = "mixdown.xml"
TRACKLIST_DIR = Path("tracklists")
TRANSCRIPT_DIR = Path("transcripts")
EPISODE_PAUSE = 30  # pauza mezi epizodami, ať Shazam nedostává souvislou palbu


def episodes_from_feed(xml_path: str) -> list[dict]:
    root = ET.parse(xml_path).getroot()
    episodes = []
    for item in root.iter("item"):
        num = item.findtext(f"{ITUNES_NS}episode")
        enclosure = item.find("enclosure")
        if num is None or enclosure is None:
            continue
        episodes.append({
            "num": int(num),
            "title": item.findtext("title", ""),
            "url": enclosure.get("url"),
        })
    return episodes


def download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)


async def process_episode(episode: dict) -> bool:
    tracklist_path = TRACKLIST_DIR / f"{episode['num']}.json"
    transcript_path = TRANSCRIPT_DIR / f"{episode['num']}.txt"
    print(f"\n=== {episode['title']} ===", file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / "episode.mp3"
        try:
            download(episode["url"], mp3)
        except Exception as exc:
            print(f"stažení selhalo: {exc}", file=sys.stderr)
            return False

        ok = True
        if not tracklist_path.exists():
            tracklist = await build_tracklist(str(mp3))
            if tracklist:
                tracklist_path.write_text(
                    json.dumps(tracklist, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
                print(f"uloženo: {tracklist_path} ({len(tracklist)} skladeb)",
                      file=sys.stderr)
            else:
                # nic nerozpoznáno (výpadek sítě / rate limit?) — neukládat,
                # ať se epizoda příště zkusí znovu
                print("tracklist: prázdný výsledek, přeskakuji uložení",
                      file=sys.stderr)
                ok = False

        if not transcript_path.exists():
            try:
                text = transcribe_intro(str(mp3))
            except Exception as exc:
                print(f"přepis selhal: {exc}", file=sys.stderr)
                text = None
            if text:
                transcript_path.write_text(text + "\n", encoding="utf-8")
                print(f"uloženo: {transcript_path}", file=sys.stderr)
            else:
                print("přepis: prázdný výsledek, přeskakuji uložení", file=sys.stderr)
                ok = False

    return ok


async def run(limit: int | None) -> None:
    TRACKLIST_DIR.mkdir(exist_ok=True)
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    missing = [e for e in episodes_from_feed(XML_FILE)
               if not (TRACKLIST_DIR / f"{e['num']}.json").exists()
               or not (TRANSCRIPT_DIR / f"{e['num']}.txt").exists()]
    if limit is not None:
        missing = missing[:limit]
    print(f"Epizod k rozpoznání: {len(missing)}", file=sys.stderr)

    for i, episode in enumerate(missing):
        await process_episode(episode)
        if i + 1 < len(missing):
            await asyncio.sleep(EPISODE_PAUSE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Doplnění tracklistů k epizodám")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, default=3,
                       help="max počet epizod za běh (výchozí 3)")
    group.add_argument("--all", action="store_true",
                       help="zpracovat všechny chybějící epizody (backfill)")
    args = parser.parse_args()

    asyncio.run(run(None if args.all else args.limit))


if __name__ == "__main__":
    main()

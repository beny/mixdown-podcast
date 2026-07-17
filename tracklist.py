"""Rozpozná skladby v MP3 mixu pomocí Shazamu (shazamio) a vrátí tracklist.

Postup: ffmpeg vyřeže krátký vzorek, shazamio ho pošle na Shazam API.
Z odpovědi se využije `matches[0].offset` (pozice vzorku uvnitř rozpoznané
skladby) → spočítá se skutečný začátek skladby v mixu. Délka skladby se
dotáhne z iTunes Lookup API a další vzorek se položí až ke konci skladby,
takže dotazů je potřeba jen o málo víc než skladeb.

Použití jako CLI:
    python tracklist.py mix.mp3 [--step 90] [--sample 12] [--json out.json]

Použití jako modul:
    tracklist = await build_tracklist("mix.mp3")
"""

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import aiohttp
from shazamio import Shazam

REQUEST_PAUSE = 2.0   # pauza mezi dotazy na Shazam, ať nenarazíme na rate limit
DEFAULT_STEP = 90.0   # základní krok vzorkování, když o skladbě nic nevíme
DEFAULT_SAMPLE = 12.0  # délka vzorku posílaného na Shazam
MIN_STEP = 45.0       # nikdy nesamplovat hustěji než po tolika sekundách
MAX_JUMP = 240.0      # a nikdy neskočit dál (edity v mixu bývají kratší než originál)
END_MARGIN = 30.0     # vzorek pokládat s rezervou před odhadovaný konec skladby


def audio_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def extract_sample(src: str, offset: float, length: float, dest: str) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(offset), "-t", str(length),
         "-i", src, "-ac", "1", "-ar", "44100", dest],
        capture_output=True, check=True,
    )


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def parse_match(result: dict) -> dict | None:
    track = result.get("track")
    if not track:
        return None
    matches = result.get("matches") or []
    offset = matches[0].get("offset") if matches else None
    adam_id = None
    for action in (track.get("hub") or {}).get("actions") or []:
        if action.get("type") == "applemusicplay" and action.get("id"):
            adam_id = action["id"]
            break
    return {
        "artist": track.get("subtitle", "?"),
        "title": track.get("title", "?"),
        "offset": offset,      # pozice vzorku uvnitř skladby (s)
        "adam_id": adam_id,    # Apple Music ID pro dotažení délky
    }


async def itunes_duration(session: aiohttp.ClientSession, adam_id: str) -> float | None:
    try:
        async with session.get(
            "https://itunes.apple.com/lookup", params={"id": adam_id},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = json.loads(await resp.text())
        for item in data.get("results", []):
            if item.get("trackTimeMillis"):
                return item["trackTimeMillis"] / 1000.0
    except Exception:
        pass
    return None


async def build_tracklist(path: str, step: float = DEFAULT_STEP,
                          sample_len: float = DEFAULT_SAMPLE) -> list[dict]:
    total = audio_duration(path)
    print(f"Délka mixu: {fmt_time(total)}", file=sys.stderr)

    shazam = Shazam()
    tracklist: list[dict] = []
    duration_cache: dict[str, float | None] = {}
    queries = 0

    async with aiohttp.ClientSession() as session:
        with tempfile.TemporaryDirectory() as tmp:
            sample = str(Path(tmp) / "sample.wav")
            t = 0.0
            prev_t = 0.0
            while t < total - sample_len / 2:
                extract_sample(path, t, min(sample_len, total - t), sample)
                try:
                    hit = parse_match(await shazam.recognize(sample))
                except Exception as exc:
                    print(f"  {fmt_time(t)}  chyba: {exc}", file=sys.stderr)
                    hit = None
                queries += 1

                next_t = t + step  # výchozí krok, když nevíme nic lepšího
                if hit is None:
                    print(f"  {fmt_time(t)}  (nerozpoznáno)", file=sys.stderr)
                    next_t = t + MIN_STEP  # jsme nejspíš v přechodu, zkusit brzy znovu
                else:
                    # skutečný začátek skladby v mixu = čas vzorku - offset ve skladbě
                    start = max(0.0, t - hit["offset"]) if hit["offset"] is not None else t
                    # DJ občas hraje jiný edit → offset lže; začátek nové skladby
                    # nesmí předběhnout předchozí vzorek (tam ještě hrálo něco jiného)
                    if tracklist and start <= tracklist[-1]["time"]:
                        start = max(prev_t, tracklist[-1]["time"] + 1)
                    key = (hit["artist"].lower(), hit["title"].lower())
                    if not tracklist or (tracklist[-1]["artist"].lower(),
                                         tracklist[-1]["title"].lower()) != key:
                        start_s = round(start)
                        tracklist.append({
                            "time": start_s, "timestamp": fmt_time(start_s),
                            "artist": hit["artist"], "title": hit["title"],
                        })
                        print(f"  {fmt_time(t)}  → {fmt_time(start)}  "
                              f"{hit['artist']} – {hit['title']}", file=sys.stderr)
                    else:
                        print(f"  {fmt_time(t)}  (stále {hit['title']})", file=sys.stderr)

                    if hit["adam_id"]:
                        if hit["adam_id"] not in duration_cache:
                            duration_cache[hit["adam_id"]] = await itunes_duration(
                                session, hit["adam_id"])
                        dur = duration_cache[hit["adam_id"]]
                        if dur and hit["offset"] is not None:
                            est_end = start + dur
                            next_t = est_end - sample_len - END_MARGIN

                prev_t = t
                t = min(max(next_t, t + MIN_STEP), t + MAX_JUMP)
                if t < total - sample_len / 2:
                    await asyncio.sleep(REQUEST_PAUSE)

    print(f"Dotazů na Shazam: {queries}", file=sys.stderr)
    return tracklist


def main() -> None:
    parser = argparse.ArgumentParser(description="Tracklist mixu přes Shazam")
    parser.add_argument("audio", help="cesta k MP3")
    parser.add_argument("--step", type=float, default=DEFAULT_STEP,
                        help=f"základní krok vzorkování v s (výchozí {DEFAULT_STEP:.0f})")
    parser.add_argument("--sample", type=float, default=DEFAULT_SAMPLE,
                        help=f"délka vzorku v s (výchozí {DEFAULT_SAMPLE:.0f})")
    parser.add_argument("--json", help="uložit výsledek i jako JSON")
    args = parser.parse_args()

    tracklist = asyncio.run(build_tracklist(args.audio, args.step, args.sample))

    print()
    for entry in tracklist:
        print(f"{entry['timestamp']}  {entry['artist']} – {entry['title']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(tracklist, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON uložen: {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()

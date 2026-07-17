from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import html
import re
from xml.dom import minidom
import requests

ET.register_namespace('itunes', 'http://www.itunes.com/dtds/podcast-1.0.dtd')

SOURCE_URL = "https://radiocolor.cz/download.php?sekce=18"
DOWNLOADED_HTML = "mixdown.html"  # latest downloaded copy
HTML_FILE = "color_music_radio.html"  # legacy fallback/local cache
OUTPUT_XML = "mixdown.xml"
TRACKLIST_DIR = Path("tracklists")  # výstupy enrich.py (Shazam)
CHAPTERS_DIR = Path("chapters")  # JSON kapitoly pro <podcast:chapters>
CHAPTERS_URL_BASE = "https://raw.githubusercontent.com/beny/mixdown-podcast/main/chapters"


def load_tracklist(episode_num):
    """Vrátí uložený tracklist epizody, nebo None když (zatím) neexistuje."""
    if episode_num is None:
        return None
    path = TRACKLIST_DIR / f"{episode_num}.json"
    if not path.exists():
        return None
    tracklist = json.loads(path.read_text(encoding="utf-8"))
    return tracklist or None


def chapter_time(seconds):
    """Čas ve formátu HH:MM:SS pro psc:chapter."""
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

def compute_pub_date(current_date_obj, next_date_obj, episode_num):
    """
    Vrátí tuple (dt_with_time, used_offset) kde dt_with_time je datetime pro pubDate.
    Offset (čas v rámci dne) se použije pouze pokud je current_date_obj ve stejném dni jako next_date_obj
    a zároveň je k dispozici kladné číslo epizody.
    """
    base_dt = current_date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_date_obj is not None and current_date_obj.date() == next_date_obj.date() and episode_num is not None and episode_num >= 0:
        offset_seconds = episode_num % 86400
        return base_dt + timedelta(seconds=offset_seconds), True
    else:
        return base_dt, False

def fetch_source_html() -> str:
    """
    Stáhne HTML ze SOURCE_URL. Při úspěchu vrátí obsah a uloží kopii do DOWNLOADED_HTML.
    Při selhání vyvolá výjimku a neprovádí žádné fallbacky.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }

    resp = requests.get(SOURCE_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    html_text = resp.text
    print(f"🌐 Staženo z webu: {SOURCE_URL} (délka {len(html_text)} znaků)")

    # Best-effort uložení stažené kopie (chyby ignorujeme)
    try:
        with open(DOWNLOADED_HTML, "w", encoding="utf-8") as out_html:
            out_html.write(html_text)
        print(f"💾 Uloženo do souboru: {DOWNLOADED_HTML}")
    except Exception:
        pass

    return html_text

# Fetch HTML (download + fallback)
html_content = fetch_source_html()

soup = BeautifulSoup(html_content, "html.parser")

# RSS struktura
rss = ET.Element("rss", {
    "version": "2.0",
    "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "xmlns:psc": "http://podlove.org/simple-chapters",
    "xmlns:podcast": "https://podcastindex.org/namespace/1.0"
})
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = "Mix DOWN"
ET.SubElement(channel, "link").text = "https://radiocolor.cz/showpage.php?name=mixdown"
ET.SubElement(channel, "description").text = "Hodina muziky od 60. let až po současnost s DJ Alešem Konopkou z Opavského studia. Pestrobarevná, převážně klubová, taneční, komerčně - nekomerční hudba namíchaná do jednoho non-stop hudebního mixu."
ET.SubElement(channel, "language").text = "cs"
ET.SubElement(channel, "generator").text = "Python script"
ET.SubElement(channel, "author").text = "Alesh Konopka"
ET.SubElement(channel, "itunes:author").text = "Alesh Konopka"

# Ikona
image = ET.SubElement(channel, "image")
ET.SubElement(image, "url").text = "https://radiocolor.cz/porady/mixdown.jpg"
ET.SubElement(image, "title").text = "Mix DOWN"
ET.SubElement(image, "link").text = "https://radiocolor.cz/showpage.php?name=mixdown"

# Zpracování epizod
rows = soup.find_all("tr", class_="z2")

if not rows:
    print("⚠️  Žádné epizody nebyly nalezeny.")
else:
    episodes = []

    for idx, row in enumerate(rows, start=1):
        cols = row.find_all("td")
        if len(cols) < 6:
            continue

        raw_title = cols[1].get_text(separator=" ").strip()
        date_text = cols[3].text.strip()
        a_tags = cols[0].find_all("a", href=True)
        if len(a_tags) < 2:
            continue

        file_link = "https://radiocolor.cz/" + a_tags[1]['href']

        match = re.search(r"MixDown[_ ]?(\d+)", raw_title, re.IGNORECASE)
        episode_num_str = match.group(1) if match else None
        episode_num = int(episode_num_str) if episode_num_str is not None else None
        episode_title = f"Mix DOWN #{episode_num_str}" if episode_num_str is not None else raw_title

        try:
            date_obj = datetime.strptime(date_text, "%d.%m.%Y")
        except ValueError:
            date_obj = datetime(1970, 1, 1)

        episodes.append({
            "title": episode_title,
            "file_link": file_link,
            "date_obj": date_obj,
            "date_text": date_text,
            "episode_num": episode_num,
            "episode_num_str": episode_num_str,
        })

    # řazení: novější datum první, a při shodném datu vyšší číslo epizody první
    episodes.sort(key=lambda e: (e["date_obj"], e["episode_num"] if e["episode_num"] is not None else -1), reverse=True)

    # generování RSS až po seřazení
    for i, e in enumerate(episodes):
        next_date_obj = episodes[i+1]["date_obj"] if i + 1 < len(episodes) else None
        dt_with_time, used_offset = compute_pub_date(e["date_obj"], next_date_obj, e["episode_num"])
        pub_date = dt_with_time.strftime("%a, %d %b %Y %H:%M:%S +0200")

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = e["title"]
        ET.SubElement(item, "enclosure", url=e["file_link"], type="audio/mpeg")
        ET.SubElement(item, "guid").text = e["file_link"]
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "author").text = "Alesh Konopka"
        if e["episode_num"] is not None:
            ET.SubElement(item, "itunes:episode").text = str(e["episode_num"])

        tracklist = load_tracklist(e["episode_num"])
        if tracklist:
            lines = [f"{t['timestamp']} {t['artist']} – {t['title']}" for t in tracklist]
            ET.SubElement(item, "description").text = "Tracklist:\n" + "\n".join(lines)

            # inline kapitoly (Podlove Simple Chapters)
            chapters = ET.SubElement(item, "psc:chapters", {"version": "1.2"})
            for t in tracklist:
                ET.SubElement(chapters, "psc:chapter", {
                    "start": chapter_time(t["time"]),
                    "title": f"{t['artist']} – {t['title']}",
                })

            # externí kapitoly (Podcasting 2.0) — JSON soubor vedle feedu
            CHAPTERS_DIR.mkdir(exist_ok=True)
            chapters_json = {
                "version": "1.2.0",
                "chapters": [
                    {"startTime": t["time"], "title": f"{t['artist']} – {t['title']}"}
                    for t in tracklist
                ],
            }
            chapters_path = CHAPTERS_DIR / f"{e['episode_num']}.json"
            chapters_path.write_text(
                json.dumps(chapters_json, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            ET.SubElement(item, "podcast:chapters", {
                "url": f"{CHAPTERS_URL_BASE}/{e['episode_num']}.json",
                "type": "application/json+chapters",
            })

# Formátovaný výstup
rough_string = ET.tostring(rss, encoding="utf-8")
parsed = minidom.parseString(rough_string)
pretty_xml = parsed.toprettyxml(indent="  ")

with open(OUTPUT_XML, "w", encoding="utf-8") as f:
    f.write(pretty_xml)

print(f"\n✅ Hotovo. Feed bez délky uložen jako: {OUTPUT_XML}")


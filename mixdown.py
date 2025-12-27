from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET
import html
import re
from xml.dom import minidom
import requests

SOURCE_URL = "https://radiocolor.cz/download.php?sekce=18"
DOWNLOADED_HTML = "mixdown.html"  # latest downloaded copy
HTML_FILE = "color_music_radio.html"  # legacy fallback/local cache
OUTPUT_XML = "mixdown.xml"

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
rss = ET.Element("rss", version="2.0")
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = "Mix DOWN"
ET.SubElement(channel, "link").text = "https://radiocolor.cz/showpage.php?name=mixdown"
ET.SubElement(channel, "description").text = "Hodina muziky od 60. let až po současnost s DJ Alešem Konopkou z Opavského studia. Pestrobarevná, převážně klubová, taneční, komerčně - nekomerční hudba namíchaná do jednoho non-stop hudebního mixu."
ET.SubElement(channel, "language").text = "cs"
ET.SubElement(channel, "generator").text = "Python script"
ET.SubElement(channel, "author").text = "Alesh Konopka"

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
        episode_title = f"Mix DOWN #{match.group(1)}" if match else raw_title

        try:
            pub_date = datetime.strptime(date_text, "%d.%m.%Y").strftime("%a, %d %b %Y 00:00:00 +0200")
        except ValueError:
            pub_date = "Thu, 01 Jan 1970 00:00:00 +0000"

        print(f"\nEpizoda {idx}")
        print(f"  Název   : {episode_title}")
        print(f"  Datum   : {date_text}")
        print(f"  Odkaz   : {file_link}")

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = episode_title
        ET.SubElement(item, "enclosure", url=file_link, type="audio/mpeg")
        ET.SubElement(item, "guid").text = file_link
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "author").text = "Alesh Konopka"

# Formátovaný výstup
rough_string = ET.tostring(rss, encoding="utf-8")
parsed = minidom.parseString(rough_string)
pretty_xml = parsed.toprettyxml(indent="  ")

with open(OUTPUT_XML, "w", encoding="utf-8") as f:
    f.write(pretty_xml)

print(f"\n✅ Hotovo. Feed bez délky uložen jako: {OUTPUT_XML}")


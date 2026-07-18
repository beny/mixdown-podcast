from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import re
from xml.dom import minidom
import requests

ET.register_namespace('itunes', 'http://www.itunes.com/dtds/podcast-1.0.dtd')

SOURCE_URL = "https://radiocolor.cz/download.php?sekce=13"
DOWNLOADED_HTML = "tanecni-party.html"  # latest downloaded copy
OUTPUT_XML = "tanecni-party.xml"


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

    try:
        with open(DOWNLOADED_HTML, "w", encoding="utf-8") as out_html:
            out_html.write(html_text)
        print(f"💾 Uloženo do souboru: {DOWNLOADED_HTML}")
    except Exception:
        pass

    return html_text


html_content = fetch_source_html()
soup = BeautifulSoup(html_content, "html.parser")

rss = ET.Element("rss", {
    "version": "2.0",
    "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
})
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = "Taneční Párty"
ET.SubElement(channel, "link").text = "https://radiocolor.cz/showpage.php?name=tanecniparty"
ET.SubElement(channel, "description").text = "Taneční Párty s Pavlem Bártou na Color Music Radio."
ET.SubElement(channel, "language").text = "cs"
ET.SubElement(channel, "generator").text = "Python script"
ET.SubElement(channel, "author").text = "Pavel Bárta"
ET.SubElement(channel, "itunes:author").text = "Pavel Bárta"

image = ET.SubElement(channel, "image")
ET.SubElement(image, "url").text = "https://radiocolor.cz/porady/tanecni_party.jpg"
ET.SubElement(image, "title").text = "Taneční Párty"
ET.SubElement(image, "link").text = "https://radiocolor.cz/showpage.php?name=tanecniparty"

rows = soup.find_all("tr", class_="z2")

if not rows:
    print("⚠️  Žádné epizody nebyly nalezeny.")
else:
    episodes = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 6:
            continue

        raw_title = cols[1].get_text(separator=" ").strip()
        date_text = cols[3].text.strip()
        a_tags = cols[0].find_all("a", href=True)
        if len(a_tags) < 2:
            continue

        file_link = "https://radiocolor.cz/" + a_tags[1]['href']

        # unikátní ID dílu -- na rozdíl od MixDown tu není číslo epizody v názvu,
        # použije se id_detail z odkazu na detail (roste s časem stejně jako epizoda)
        detail_match = re.search(r"id_detail=(\d+)", a_tags[0]['href'])
        episode_num = int(detail_match.group(1)) if detail_match else None

        # web vždy připojí na konec titulku výchozího moderátora -- odstranit,
        # a "N. hodina Pavel Bárta" zkrátit na "N.", autora dát zvlášť
        # (u speciálů s hostem zůstává celé jméno/jména v autorovi)
        title_text = raw_title
        if title_text.endswith(" Pavel Bárta"):
            title_text = title_text[: -len(" Pavel Bárta")]

        hour_match = re.match(r"^(.*) - (\d+)\.\s*hodina$", title_text)
        if hour_match:
            episode_title = f"{hour_match.group(1).strip()} - {hour_match.group(2)}. hodina"
            episode_author = "Pavel Bárta"
        else:
            author_match = re.match(r"^(.*) - (.+)$", title_text)
            if author_match:
                episode_title = author_match.group(1).strip()
                episode_author = author_match.group(2).strip()
            else:
                episode_title = title_text
                episode_author = "Pavel Bárta"

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
            "author": episode_author,
        })

    episodes.sort(key=lambda e: (e["date_obj"], e["episode_num"] if e["episode_num"] is not None else -1), reverse=True)

    for i, e in enumerate(episodes):
        next_date_obj = episodes[i + 1]["date_obj"] if i + 1 < len(episodes) else None
        dt_with_time, used_offset = compute_pub_date(e["date_obj"], next_date_obj, e["episode_num"])
        pub_date = dt_with_time.strftime("%a, %d %b %Y %H:%M:%S +0200")

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = e["title"]
        ET.SubElement(item, "enclosure", url=e["file_link"], type="audio/mpeg")
        ET.SubElement(item, "guid").text = e["file_link"]
        ET.SubElement(item, "pubDate").text = pub_date
        ET.SubElement(item, "author").text = e["author"]
        ET.SubElement(item, "itunes:author").text = e["author"]

rough_string = ET.tostring(rss, encoding="utf-8")
parsed = minidom.parseString(rough_string)
pretty_xml = parsed.toprettyxml(indent="  ")

with open(OUTPUT_XML, "w", encoding="utf-8") as f:
    f.write(pretty_xml)

print(f"\n✅ Hotovo. Feed uložen jako: {OUTPUT_XML}")

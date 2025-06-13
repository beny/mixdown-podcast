from bs4 import BeautifulSoup
from datetime import datetime
import xml.etree.ElementTree as ET
import html
import re
from xml.dom import minidom

HTML_FILE = "color_music_radio.html"
OUTPUT_XML = "color_music_radio_feed.xml"

with open(HTML_FILE, "r", encoding="utf-8") as f:
    soup_outer = BeautifulSoup(f, "html.parser")

all_text = "\n".join(p.get_text() for p in soup_outer.find_all("p"))
decoded_html = html.unescape(all_text)
soup = BeautifulSoup(decoded_html, "html.parser")

# RSS struktura
rss = ET.Element("rss", version="2.0")
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = "COLOR Music Radio - MixDown"
ET.SubElement(channel, "link").text = "https://radiocolor.cz"
ET.SubElement(channel, "description").text = "MixDown show by Alesh Konopka"
ET.SubElement(channel, "language").text = "cs"
ET.SubElement(channel, "generator").text = "Python script"

# Ikona
image = ET.SubElement(channel, "image")
ET.SubElement(image, "url").text = "https://radiocolor.cz/image/color_logo500x500.jpg"
ET.SubElement(image, "title").text = "COLOR Music Radio"
ET.SubElement(image, "link").text = "https://radiocolor.cz"

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
        ET.SubElement(item, "description").text = episode_title  # bez délky
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

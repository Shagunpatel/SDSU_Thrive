# yourapp/utils/sdsu_scraper.py
from __future__ import annotations
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import List, Tuple

DEFAULT_URL = "https://sacd.sdsu.edu/cps/our-services-and-programs"

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def parse_services(html: str, base_url: str) -> List[Tuple[str, str]]:
    """
    Returns [(name, url), ...] for program/service links in the main content.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup.find("div", {"id": "content"}) or soup

    rows: List[Tuple[str, str]] = []
    for a in main.find_all("a", href=True):
        name = (a.get_text(strip=True) or "").strip()
        href = a["href"].strip()
        # print(name, href)
        if name in ["Disability Services","Future Students", "Current Students", "Faculty/Staff","Alumni Home","Campus Directory",
        "San Diego State University","SDSU Home","C&PS Home","Maps & Directions","COVID-19 Updates","COVID-19 Resources",
        "COVID-19 Self Care"]:
            continue
        if name.strip() == "Contact Us":
            name="Contact Information"
        if not name:
            continue
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if name.lower() in {"learn more", "read more"}:
            continue

        full = urljoin(base_url, href)
        rows.append((name, full))

    # De-dup while preserving order
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for name, link in rows:
        key = (name.lower(), link.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, link))
    return deduped

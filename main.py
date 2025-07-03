from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel, HttpUrl
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter, Retry
from urllib.parse import urljoin, urlparse, urldefrag
from typing import List, Set, Tuple
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO)

# Setup HTTP session with retry
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Konstante für erlaubte Bildtypen
ALLOWED_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".svg"]

app = FastAPI(
    title="kampagnen-api-nojs",
    description="JS-freie Website-Analyse für Bilder, Logos und Text",
    version="1.0"
)

class AnalyzeResponse(BaseModel):
    url: HttpUrl
    title: str
    text: str
    images: List[HttpUrl]

def extract_images(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: Set[str] = set()

    for tag in soup.find_all(["img", "link", "meta"]):
        src = tag.get("src") or tag.get("href") or tag.get("content")
        if not src:
            continue
        absolute = urljoin(base_url, src)
        path = urlparse(absolute).path.lower()
        if any(path.endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS):
            urls.add(absolute)

    return list(urls)

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for elem in soup(["script", "style"]):
        elem.decompose()
    return soup.get_text(separator=" ", strip=True)

def crawl_site(start_url: str, max_pages: int = 10, max_images: int = 100) -> Tuple[str, str, List[str]]:
    visited: Set[str] = set()
    queue: List[str] = [start_url]
    all_images: Set[str] = set()
    full_text: List[str] = []
    title = ""
    start_domain = urlparse(start_url).netloc.split(":")[0].lstrip("www.")

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        logging.info(f"Crawling: {url}")

        try:
            resp = session.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except requests.RequestException as e:
            logging.warning(f"Request failed for {url}: {e}")
            continue

        html = resp.text

        if not title:
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                title = title_tag.string.strip()

        full_text.append(extract_text(html))

        for img in extract_images(html, url):
            all_images.add(img)
            if len(all_images) >= max_images:
                logging.info("Max image limit reached.")
                break

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            link = urldefrag(a["href"])[0]
            link_domain = urlparse(link).netloc.split(":")[0].lstrip("www.")
            if link_domain.endswith(start_domain) and link not in visited:
                queue.append(link)

    return title, " ".join(full_text), list(all_images)

@app.get("/crawl-analyze", response_model=AnalyzeResponse)
def crawl_analyze(
    url: HttpUrl = Query(..., description="Website-Start-URL, inkl. http(s)://"),
    max_pages: int = Query(10, ge=1, le=50, description="Max Seiten zum Crawlen (1–50)")
) -> AnalyzeResponse:
    title, text, images = crawl_site(str(url), max_pages)

    if not title and not text and not images:
        raise HTTPException(status_code=404, detail="Keine Daten gefunden oder Seite nicht erreichbar")

    return AnalyzeResponse(url=url, title=title, text=text, images=images)

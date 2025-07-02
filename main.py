from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel, HttpUrl
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin
from typing import List, Set, Tuple

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
        lower = src.lower()
        if any(lower.endswith(ext) or ext in lower for ext in [".png", ".jpg", ".jpeg", ".svg"]):
            urls.add(urljoin(base_url, src))
    return list(urls)

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for elem in soup(["script", "style"]):
        elem.decompose()
    return soup.get_text(separator=" ", strip=True)

def crawl_site(start_url: str, max_pages: int = 10) -> Tuple[str, str, List[str]]:
    visited: Set[str] = set()
    queue: List[str] = [start_url]
    all_images: Set[str] = set()
    title: str = ""
    full_text: List[str] = []

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except Exception:
            continue
        html = resp.text
        if not title:
            page_soup = BeautifulSoup(html, "html.parser")
            title_tag = page_soup.find("title")
            if title_tag and title_tag.string:
                title = title_tag.string.strip()
        full_text.append(extract_text(html))
        for img in extract_images(html, url):
            all_images.add(img)
        page_soup = BeautifulSoup(html, "html.parser")
        for a in page_soup.find_all("a", href=True):
            link = urljoin(url, a["href"])
            if link.startswith(start_url) and link not in visited:
                queue.append(link)

    return title, " ".join(full_text), list(all_images)

@app.get("/crawl-analyze", response_model=AnalyzeResponse)
def crawl_analyze(
    url: str = Query(..., description="Website-Start-URL, inkl. http(s)://"),
    max_pages: int = Query(10, ge=1, le=50, description="Max Seiten zum Crawlen (1-50)")
) -> AnalyzeResponse:
    title, text, images = crawl_site(url, max_pages)
    if not title and not text and not images:
        raise HTTPException(status_code=404, detail="Keine Daten gefunden oder Seite nicht erreichbar")
    return AnalyzeResponse(url=url, title=title, text=text, images=images)

import re
import requests
import os
import time
import sys
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.seirsanduk.us"
OUTPUT_FILE = "tv.m3u"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_CHANNELS = 100
MAX_RUNTIME_SECONDS = 500
START_TIME = time.time()

def block_aggressively(route):
    if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"]:
        route.abort()
    else:
        route.continue_()

def get_channel_list(page):
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        hrefs = page.eval_on_selector_all("a", "elements => elements.map(e => e.href)")
        channels = []
        pattern = r"seirsanduk\.us/([\w-]+)-online"
        for href in hrefs:
            match = re.search(pattern, href)
            if match:
                channel_id = match.group(1)
                if channel_id not in channels:
                    channels.append(channel_id)
        channels.sort()
        return channels[:MAX_CHANNELS]
    except Exception:
        return []

def is_link_working(url):
    headers = {"Referer": "https://glebul.com", "User-Agent": UA}
    try:
        with requests.get(url, headers=headers, timeout=10, stream=True) as r:
            return r.status_code == 200
    except:
        return False

def get_stream_for_channel(browser, channel_id):
    if time.time() - START_TIME > MAX_RUNTIME_SECONDS:
        return "STOP"

    channel_url = f"{BASE_URL}/{channel_id}-online"
    context = browser.new_context(user_agent=UA)
    page = context.new_page()
    page.route("**/*", block_aggressively)
    
    found_link = None
    try:
        with page.expect_request(lambda request: "index.m3u8" in request.url, timeout=25000) as req_info:
            page.goto(channel_url, wait_until="domcontentloaded", timeout=25000)
            found_link = req_info.value.url
    except:
        pass
    
    page.close()
    context.close()

    if found_link and is_link_working(found_link):
        return found_link
    return None

def run():
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        temp_context = browser.new_context(user_agent=UA)
        temp_page = temp_context.new_page()
        temp_page.route("**/*", block_aggressively)
        
        channel_ids = get_channel_list(temp_page)
        temp_context.close()
        
        if not channel_ids:
            browser.close()
            return

        playlist_entries = []
        for cid in channel_ids:
            stream_url = get_stream_for_channel(browser, cid)
            if stream_url == "STOP":
                break
            if stream_url:
                playlist_entries.append((cid, stream_url))

        if playlist_entries:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for name, url in playlist_entries:
                    f.write(f"\n#EXTINF:-1, {name.upper()}\n")
                    f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
                    f.write(f"#EXTVLCOPT:http-referrer=https://glebul.com\n")
                    f.write(f"{url}|User-Agent={UA}&Referer=https://glebul.com\n")
        
        browser.close()

if __name__ == "__main__":
    run()

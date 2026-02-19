import re
import requests
import os
import time
import subprocess
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.seirsanduk.us"
OUTPUT_FILE = "tv.m3u"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REFERER = "https://glebul.com"
MAX_CHANNELS = 100
MAX_RUNTIME_SECONDS = 600 # Increased slightly for ffprobe overhead
START_TIME = time.time()

def block_aggressively(route):
    if route.request.resource_type in ["image", "stylesheet", "font", "media", "other"]:
        route.abort()
    else:
        route.continue_()

def is_link_working(url):
    """
    Uses ffprobe to verify the stream has valid media content.
    This catches 403, 404, and 'empty' streams that requests might miss.
    """
    # Build the ffprobe command
    # -v error: only show critical errors
    # -show_entries: minimize output
    # -headers: pass the required UA and Referer
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-headers', f"User-Agent: {UA}\r\nReferer: {REFERER}\r\n",
        url
    ]
    
    try:
        # Run ffprobe with a 10-second timeout
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
        # If returncode is 0, the stream is valid and readable
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False

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

def get_stream_for_channel(browser, channel_id):
    if time.time() - START_TIME > MAX_RUNTIME_SECONDS:
        return "STOP"

    channel_url = f"{BASE_URL}/{channel_id}-online"
    context = browser.new_context(user_agent=UA)
    page = context.new_page()
    page.route("**/*", block_aggressively)
    
    found_link = None
    try:
        # Looking for the .m3u8 source
        with page.expect_request(lambda request: "index.m3u8" in request.url, timeout=20000) as req_info:
            page.goto(channel_url, wait_until="domcontentloaded", timeout=20000)
            found_link = req_info.value.url
    except:
        pass
    
    page.close()
    context.close()

    if found_link:
        print(f"Checking stream for {channel_id}...")
        if is_link_working(found_link):
            print(f"  [SUCCESS] {channel_id} is live.")
            return found_link
        else:
            print(f"  [FAILED] {channel_id} returned error or no data.")
    return None

def run():
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        temp_context = browser.new_context(user_agent=UA)
        temp_page = temp_context.new_page()
        temp_page.route("**/*", block_aggressively)
        
        channel_ids = get_channel_list(temp_page)
        temp_context.close()
        
        if not channel_ids:
            print("No channels found.")
            browser.close()
            return

        playlist_entries = []
        for cid in channel_ids:
            stream_url = get_stream_for_channel(browser, cid)
            if stream_url == "STOP":
                print("Runtime limit reached, finishing up...")
                break
            if stream_url:
                playlist_entries.append((cid, stream_url))

        if playlist_entries:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for name, url in playlist_entries:
                    f.write(f"\n#EXTINF:-1, {name.upper()}\n")
                    f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
                    f.write(f"#EXTVLCOPT:http-referrer={REFERER}\n")
                    f.write(f"{url}|User-Agent={UA}&Referer={REFERER}\n")
            print(f"\nCreated {OUTPUT_FILE} with {len(playlist_entries)} working channels.")
        
        browser.close()

if __name__ == "__main__":
    run()

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
MAX_RUNTIME_SECONDS = 900 # Increased to allow for retries
MAX_RETRIES_PER_CHANNEL = 1 # Prevents infinite loops on dead channels
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
    # Some streams require specific headers to even validate the M3U8
    headers = {"Referer": "https://glebul.com", "User-Agent": UA}
    try:
        # Using head request is faster, falling back to GET if needed
        response = requests.head(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return True
        r = requests.get(url, headers=headers, timeout=5, stream=True)
        return r.status_code == 200
    except:
        return False

def get_stream_for_channel(browser, channel_id):
    retries = 0
    channel_url = f"{BASE_URL}/{channel_id}-online"
    
    # Keep trying until we find a working link or hit retry limit/timeout
    while retries < MAX_RETRIES_PER_CHANNEL:
        if time.time() - START_TIME > MAX_RUNTIME_SECONDS:
            return "STOP"

        print(f"  > Attempt {retries + 1} for {channel_id}...")
        
        context = browser.new_context(user_agent=UA)
        page = context.new_page()
        page.route("**/*", block_aggressively)
        
        found_link = None
        try:
            # Wait for the network request that contains the stream URL
            with page.expect_request(lambda request: "index.m3u8" in request.url, timeout=20000) as req_info:
                page.goto(channel_url, wait_until="domcontentloaded", timeout=20000)
                found_link = req_info.value.url
        except Exception:
            pass
        
        page.close()
        context.close()

        if found_link:
            print(f"    Link found, testing: {found_link[:50]}...")
            if is_link_working(found_link):
                print(f"    [SUCCESS] Working link found for {channel_id}")
                return found_link
            else:
                print(f"    [INVALID] Link returned 404/Error. Retrying...")
        else:
            print(f"    [TIMEOUT] No link intercepted. Retrying...")
        
        retries += 1
        time.sleep(2) # Short cooldown before refreshing

    print(f"  [SKIPPING] Could not find a working link for {channel_id} after {MAX_RETRIES_PER_CHANNEL} tries.")
    return None

def run():
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        
        # 1. Get List
        temp_context = browser.new_context(user_agent=UA)
        temp_page = temp_context.new_page()
        temp_page.route("**/*", block_aggressively)
        channel_ids = get_channel_list(temp_page)
        temp_context.close()
        
        if not channel_ids:
            print("No channels found.")
            browser.close()
            return

        print(f"Found {len(channel_ids)} channels. Starting stream verification...")

        # 2. Process Channels
        playlist_entries = []
        for cid in channel_ids:
            print(f"Processing: {cid}")
            stream_url = get_stream_for_channel(browser, cid)
            
            if stream_url == "STOP":
                print("Global timeout reached. Stopping.")
                break
                
            if stream_url:
                playlist_entries.append((cid, stream_url))

        # 3. Write M3U
        if playlist_entries:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for name, url in playlist_entries:
                    f.write(f"\n#EXTINF:-1, {name.upper()}\n")
                    f.write(f"#EXTVLCOPT:http-user-agent={UA}\n")
                    f.write(f"#EXTVLCOPT:http-referrer=https://glebul.com\n")
                    f.write(f"{url}|User-Agent={UA}&Referer=https://glebul.com\n")
            print(f"Done! Created {OUTPUT_FILE} with {len(playlist_entries)} working links.")
        
        browser.close()

if __name__ == "__main__":
    run()

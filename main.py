from flask import Flask, request, jsonify, render_template, send_file, send_from_directory
from flask_cors import CORS
import requests
import os
import json
import logging
import re
from urllib.parse import urlparse, quote
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import threading
import atexit

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variable for the browser instance
browser = None
browser_lock = threading.Lock()

def initialize_browser():
    """Initialize the Chrome browser with necessary options"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_page_load_timeout(30)
    return driver

def get_browser():
    """Get or create browser instance"""
    global browser
    with browser_lock:
        if browser is None:
            browser = initialize_browser()
        return browser

def cleanup_browser():
    """Cleanup browser instance on shutdown"""
    global browser
    if browser:
        browser.quit()

# Register cleanup function
atexit.register(cleanup_browser)

def clean_instagram_url(url):
    """Clean and validate Instagram URL"""
    try:
        # Remove query parameters and trailing slash
        url = url.split('?')[0].rstrip('/')
        
        # Ensure it's an Instagram URL
        if 'instagram.com' not in url:
            return None, "Not an Instagram URL"
            
        # Extract the post/reel ID
        parts = url.split('/')
        if 'p' in parts or 'reel' in parts:
            # Find the index after 'p' or 'reel'
            try:
                idx = parts.index('p')
            except ValueError:
                try:
                    idx = parts.index('reel')
                except ValueError:
                    return None, "Invalid Instagram URL format"
            
            # Get the ID if it exists
            if idx + 1 < len(parts):
                post_id = parts[idx + 1]
                return post_id, None
                
        return None, "Could not extract post ID from URL"
        
    except Exception as e:
        logger.error(f"Error cleaning URL: {str(e)}")
        return None, str(e)

def download_instagram_video(url):
    """Download Instagram video using Instagram's public API"""
    try:
        # Clean the URL first
        post_id, error = clean_instagram_url(url)
        if error:
            return None, error
            
        logger.info(f"Extracted post ID: {post_id}")
        
        # First try Instagram's public API
        api_url = f"https://www.instagram.com/p/{post_id}/?__a=1&__d=dis"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }
        
        logger.info(f"Trying Instagram API: {api_url}")
        response = requests.get(api_url, headers=headers)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if 'items' in data:
                    for item in data['items']:
                        if 'video_versions' in item:
                            # Get the highest quality video URL
                            video_url = item['video_versions'][0]['url']
                            logger.info(f"Found video URL from API: {video_url}")
                            return video_url, None
                            
                if 'graphql' in data:
                    media = data['graphql']['shortcode_media']
                    if 'video_url' in media:
                        video_url = media['video_url']
                        logger.info(f"Found video URL from GraphQL: {video_url}")
                        return video_url, None
            except Exception as e:
                logger.error(f"Error parsing API response: {str(e)}")
        
        # If API fails, try web scraping
        logger.info("API failed, trying web scraping...")
        driver = get_browser()
        
        # Navigate to the URL
        logger.info(f"Navigating to URL: {url}")
        driver.get(url)
        
        # Wait for content to load
        time.sleep(3)  # Give some time for dynamic content to load
        
        # Try multiple selectors for video elements
        video_selectors = [
            "video",
            "video source",
            "meta[property='og:video']",
            "meta[property='og:video:secure_url']"
        ]
        
        for selector in video_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    if selector.startswith("meta"):
                        video_url = element.get_attribute("content")
                    else:
                        video_url = element.get_attribute("src")
                        
                    if video_url and not video_url.startswith("blob:"):
                        logger.info(f"Found video URL using selector {selector}: {video_url}")
                        return video_url, None
            except Exception as e:
                logger.error(f"Error with selector {selector}: {str(e)}")
        
        # Try to find in page source
        page_source = driver.page_source
        video_patterns = [
            r'"video_url":"([^"]+)"',
            r'"playbackUrl":"([^"]+)"',
            r'"contentUrl":"([^"]+)"',
            r'"video":{"url":"([^"]+)"',
            r'<meta property="og:video" content="([^"]+)"',
            r'<meta property="og:video:secure_url" content="([^"]+)"',
            r'video_versions":\[(.*?)\]'
        ]
        
        for pattern in video_patterns:
            matches = re.findall(pattern, page_source)
            if matches:
                if pattern.endswith('\]'):
                    # Handle video_versions array
                    video_versions = matches[0]
                    url_matches = re.findall(r'"url":"([^"]+)"', video_versions)
                    if url_matches:
                        video_url = url_matches[0].replace('\\u0026', '&').replace('\\/', '/')
                        if not video_url.startswith('blob:'):
                            logger.info(f"Found video URL in video_versions: {video_url}")
                            return video_url, None
                else:
                    video_url = matches[0].replace('\\u0026', '&').replace('\\/', '/')
                    if not video_url.startswith('blob:'):
                        logger.info(f"Found video URL in source: {video_url}")
                        return video_url, None
        
        # Try network requests
        script = """
        return new Promise((resolve) => {
            let videoUrl = null;
            const observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (entry.initiatorType === 'video' || 
                        entry.name.includes('.mp4') || 
                        entry.name.includes('/video/')) {
                        videoUrl = entry.name;
                        break;
                    }
                }
            });
            observer.observe({ entryTypes: ['resource'] });
            
            // Force video load
            const videos = document.getElementsByTagName('video');
            for (const video of videos) {
                video.currentTime = 1;
                if (video.paused) {
                    video.play().catch(() => {});
                }
            }
            
            // Wait a bit for the request to be captured
            setTimeout(() => {
                resolve(videoUrl);
            }, 3000);
        });
        """
        video_url = driver.execute_async_script(script)
        if video_url and not video_url.startswith('blob:'):
            logger.info(f"Found video URL from network requests: {video_url}")
            return video_url, None
            
        return None, "Could not find video URL. Please make sure:\n1. The URL is correct\n2. The post is public\n3. The post contains a video"

    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        return None, f"Error downloading video: {str(e)}"

def extract_video_thumbnail(url, post_id):
    """Extract video thumbnail from Instagram post"""
    try:
        driver = get_browser()
        driver.get(url)
        
        # Reduced wait time
        time.sleep(1)
        
        # Try multiple methods to get thumbnail in parallel
        thumbnail_url = None
        
        # Method 1: Try to get from meta tags (fastest)
        meta_tags = driver.find_elements(By.CSS_SELECTOR, 'meta[property="og:image"]')
        if meta_tags:
            thumbnail_url = meta_tags[0].get_attribute('content')
            if thumbnail_url:
                logger.info("Found thumbnail in meta tags")
                return process_thumbnail(thumbnail_url, post_id)
        
        # Method 2: Try to get from video poster
        video_elements = driver.find_elements(By.TAG_NAME, 'video')
        if video_elements:
            thumbnail_url = video_elements[0].get_attribute('poster')
            if thumbnail_url:
                logger.info("Found thumbnail in video poster")
                return process_thumbnail(thumbnail_url, post_id)
        
        # Method 3: Try to get from image elements
        img_elements = driver.find_elements(By.CSS_SELECTOR, 'img[class*="post"]')
        for img in img_elements:
            src = img.get_attribute('src')
            if src and 'scontent' in src:
                thumbnail_url = src
                logger.info("Found thumbnail in image elements")
                return process_thumbnail(thumbnail_url, post_id)
        
        return None
    except Exception as e:
        logger.error(f"Error extracting thumbnail: {str(e)}")
        return None

def process_thumbnail(thumbnail_url, post_id):
    """Process and save thumbnail"""
    try:
        timestamp = int(time.time())
        download_dir = os.path.join(os.getcwd(), "downloads", str(timestamp))
        os.makedirs(download_dir, exist_ok=True)
        
        thumbnail_file = os.path.join(download_dir, f"thumbnail_{post_id}.jpg")
        
        # Download thumbnail with a timeout
        response = requests.get(thumbnail_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/'
        }, timeout=5)
        
        if response.status_code == 200:
            with open(thumbnail_file, 'wb') as f:
                f.write(response.content)
            return f"/downloads/thumbnail_{post_id}.jpg"
        return None
    except Exception as e:
        logger.error(f"Error processing thumbnail: {str(e)}")
        return None

@app.route("/")
def index():
    return render_template('index.html')

@app.route('/downloads/<path:filename>')
def download_file(filename):
    """Serve the downloaded file"""
    try:
        # Get the base downloads directory
        downloads_dir = os.path.join(os.getcwd(), "downloads")
        
        # Find the file in any subdirectory
        for root, dirs, files in os.walk(downloads_dir):
            if filename in files:
                # Get the relative path from downloads directory
                rel_path = os.path.relpath(root, downloads_dir)
                return send_from_directory(
                    os.path.join(downloads_dir, rel_path),
                    filename,
                    as_attachment=True,
                    download_name=filename
                )
        
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/prepare-download", methods=["POST"])
def prepare_download():
    """First phase: Extract thumbnail and prepare download"""
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({"error": "Missing URL in request"}), 400

        url = data["url"]
        logger.info(f"Preparing download for URL: {url}")

        # Validate URL
        if not url.startswith(('http://', 'https://')):
            return jsonify({"error": "Invalid URL format"}), 400

        # Clean the URL first
        post_id, error = clean_instagram_url(url)
        if error:
            return jsonify({"error": error}), 400

        # Extract thumbnail first (faster operation)
        thumbnail_url = extract_video_thumbnail(url, post_id)
        
        if thumbnail_url:
            return jsonify({
                "status": "success",
                "message": "Video ready for download",
                "thumbnail_url": thumbnail_url,
                "post_id": post_id
            })
        else:
            return jsonify({"error": "Could not prepare video for download"}), 400

    except Exception as e:
        logger.error(f"Error in prepare_download: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/start-download", methods=["POST"])
def start_download():
    """Second phase: Actually download the video"""
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({"error": "Missing URL in request"}), 400

        url = data["url"]
        logger.info(f"Starting download for URL: {url}")

        # Download video
        video_url, error = download_instagram_video(url)
        
        if error:
            logger.error(f"Download failed: {error}")
            return jsonify({"error": error}), 400

        if not video_url:
            return jsonify({"error": "Could not find video URL"}), 404

        # Create downloads directory if it doesn't exist
        timestamp = int(time.time())
        download_dir = os.path.join(os.getcwd(), "downloads", str(timestamp))
        os.makedirs(download_dir, exist_ok=True)
        
        # Create filename with timestamp
        filename = f"video_{timestamp}.mp4"
        video_file = os.path.join(download_dir, filename)

        # Download the video file
        logger.info(f"Downloading video from URL: {video_url}")
        video_response = requests.get(video_url, stream=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.instagram.com/'
        }, timeout=30)
        
        if video_response.status_code == 200:
            total_size = 0
            with open(video_file, 'wb') as f:
                for chunk in video_response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total_size += len(chunk)
            
            # Verify the file exists and has content
            if not os.path.exists(video_file):
                logger.error("Video file was not created")
                return jsonify({"error": "Failed to create video file"}), 500
                
            if os.path.getsize(video_file) == 0:
                logger.error("Video file is empty")
                os.remove(video_file)
                return jsonify({"error": "Downloaded file is empty"}), 500
                
            if total_size < 1024:  # Less than 1KB is probably an error
                logger.error(f"Video file too small: {total_size} bytes")
                os.remove(video_file)
                return jsonify({"error": "Downloaded file is too small"}), 500

            logger.info(f"Video successfully downloaded to: {video_file} (Size: {total_size} bytes)")
            
            return jsonify({
                "status": "success",
                "message": f"Video downloaded successfully ({total_size} bytes)",
                "download_url": f"/downloads/{filename}",
                "filename": filename
            })
        else:
            logger.error(f"Failed to download video file: {video_response.status_code}")
            return jsonify({"error": f"Failed to download video file: HTTP {video_response.status_code}"}), 400

    except requests.Timeout:
        logger.error("Request timed out while downloading video")
        return jsonify({"error": "Download timed out"}), 500
    except Exception as e:
        logger.error(f"Error in start_download: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Create downloads directory if it doesn't exist
    os.makedirs("downloads", exist_ok=True)
    # Initialize browser at startup
    get_browser()
    app.run(host="0.0.0.0", port=8000, debug=True)

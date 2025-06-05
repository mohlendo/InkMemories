import logging
import os
import re
import shutil
from logging import Logger
from pathlib import Path
from typing import List, Dict, Optional, Any

import json5
import requests

from common.display_config import DisplayConfig

DISPLAY_CONFIG_FILE_PATH = './display_config.json'
# --- Defining the ImageInfo structure ---
ImageInfo = Dict[str, Any]


class PictureService:
    logger: Logger
    display_config: DisplayConfig

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.DEBUG)
        self.display_config = DisplayConfig(self.logger, DISPLAY_CONFIG_FILE_PATH)

    def get_shared_album_html(self, album_shared_url: str) -> str:
        """
        Python equivalent of getSharedAlbumHtml using the synchronous 'requests' library.
        Includes basic retry logic.
        """
        retries = 4
        delay_seconds = 1  # 1000 milliseconds = 1 second

        for i in range(retries + 1):
            try:
                self.logger.info(f"Fetching HTML from {album_shared_url} (Attempt {i + 1}/{retries + 1})...")
                response = requests.get(album_shared_url, timeout=30)
                response.raise_for_status()  # Raises an exception for 4xx/5xx responses
                return response.text
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Request failed: {e}.")
                if i < retries:
                    requests.time.sleep(delay_seconds)
                else:
                    raise  # Re-raise if all retries fail

    def parse_phase_1(self, input_html: str) -> Optional[str]:
        """
        Python equivalent of parsePhase1. Extracts the longest JSON-like string.
        """
        re_pattern = r"(?<=AF_initDataCallback\()(?=.*data)(\{[\s\S]*?)(\);<\/script>)"

        longest_match_content = ""
        for match in re.finditer(re_pattern, input_html):
            current_match_content = match.group(1)
            if len(current_match_content) > len(longest_match_content):
                longest_match_content = current_match_content

        return longest_match_content if longest_match_content else None

    def parse_phase_2(self, input_str: str) -> Optional[Any]:
        """
        Python equivalent of parsePhase2 using json5.loads.
        This will handle JavaScript object literal features like unquoted keys,
        single-quoted strings, trailing commas, and comments.
        """
        try:
            return json5.loads(input_str)
        except Exception as e:
            self.logger.error(f"Error parsing JS object with json5 in parse_phase_2: {e}")
            self.logger.error(f"Problematic string start: {input_str[:200]}...")
            return None

    # Type Guard for ContainData
    def is_contain_data(self, obj: Any) -> bool:
        """Checks if an object is a dictionary and contains a 'data' key."""
        return isinstance(obj, dict) and 'data' in obj

    def is_array(self, obj: Any) -> bool:
        """Checks if an object is a list."""
        return isinstance(obj, list)

    def parse_phase_3(self, input_data: Any) -> Optional[List[ImageInfo]]:
        """
        Python equivalent of parsePhase3. Parses the structured data into ImageInfo objects.
        """
        if not self.is_contain_data(input_data):
            return None

        d = input_data.get('data')
        if not self.is_array(d) or not d:
            return None

        # Assuming d[1] is the main array of image entries based on observed Google Photos structure
        arr = d[1]
        if not self.is_array(arr):
            return None

        parsed_images: List[ImageInfo] = []
        for e in arr:
            # Each 'e' is expected to be an array with at least 6 elements
            if not self.is_array(e) or len(e) < 6:
                continue

            uid = e[0]
            image_update_date = e[2]
            album_add_date = e[5]

            # Basic type checks for the main elements
            if not isinstance(uid, str) or not isinstance(image_update_date, (int, float)) or not isinstance(
                    album_add_date, (int, float)):
                continue

            detail = e[1]  # This is expected to be another nested array for URL, width, height
            if not self.is_array(detail) or len(detail) < 3:
                continue

            url = detail[0]
            width = detail[1]
            height = detail[2]

            # Basic type checks for image details
            if not isinstance(url, str) or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                continue

            # Append the parsed ImageInfo
            parsed_images.append({"uid": uid, "url": url, "width": int(width), "height": int(height),
                                  "imageUpdateDate": int(image_update_date), "albumAddDate": int(album_add_date), })

        return parsed_images if parsed_images else None

    # --- The converted fetch_image_urls function ---

    def fetch_image_urls(self, album_shared_url: str) -> Optional[List[ImageInfo]]:
        """
        Python equivalent of the fetchImageUrls function, using synchronous requests.
        """
        try:
            html = self.get_shared_album_html(album_shared_url)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching HTML: {e}")
            return None

        ph1 = self.parse_phase_1(html)
        if ph1 is None:
            self.logger.error("Phase 1 parsing failed: Could not extract data block from HTML.")
            return None

        ph2 = self.parse_phase_2(ph1)
        if ph2 is None:
            self.logger.error("Phase 2 parsing failed: Could not parse JSON/JS object data.")
            return None

        result = self.parse_phase_3(ph2)
        if result is None:
            self.logger.error("Phase 3 parsing failed: Could not extract image info from parsed data.")
            return None

        return result

    def sync_images_to_folder(self):
        """
        Downloads images from a Google Photos album to a local folder,
        skipping existing files and removing deleted ones.
        """
        download_path = Path(self.display_config.config['display']['image_source_dir'])
        download_path.mkdir(parents=True, exist_ok=True)  # Create folder if it doesn't exist

        self.logger.info(f"\n--- Syncing images to: {download_path.resolve()} ---")

        # 1. Get current album image info
        album_images = self.fetch_image_urls(self.display_config.config['display']['google_photos_album'])
        if album_images is None:
            self.logger.error("Failed to retrieve album image information. Cannot sync.")
            return

        # Create a set of UIDs from the album for quick lookup
        album_uids = {img['uid'] for img in album_images}
        album_uid_to_info = {img['uid']: img for img in album_images}

        self.logger.info(f"Found {len(album_images)} images in the album.")

        # 2. Get existing local files
        # Map local file stems (UIDs) to their full paths
        local_files: Dict[str, Path] = {}
        for item in download_path.iterdir():
            if item.is_file():
                # Assume filename is UID.extension, so item.stem gives UID
                local_files[item.stem] = item

        self.logger.info(f"Found {len(local_files)} images in the local folder.")

        # 3. Download new/updated images
        download_count = 0
        for img_info in album_images:
            uid = img_info['uid']
            original_url = img_info['url']
            width = img_info['width']
            height = img_info['height']

            # Construct the dimensioned URL
            dimension_string = f"=w{width}-h{height}"
            cleaned_url = re.sub(r'=[swh]\d+(-h\d+)?$', '', original_url)
            download_url = f"{cleaned_url}{dimension_string}"

            # Extract file extension from the original URL (e.g., .jpg, .png)
            file_extension = Path(original_url).suffix
            if not file_extension:
                file_extension = ".jpg"  # Default to .jpg if no extension found

            filename = f"{uid}{file_extension}"
            local_file_path = download_path / filename

            if local_file_path.exists():
                self.logger.info(f"  Skipping '{filename}': already exists locally.")
            else:
                self.logger.info(f"  Downloading '{filename}' (Dims: {width}x{height}) from {download_url}...")
                try:
                    with requests.get(download_url, stream=True, timeout=60) as r:
                        r.raise_for_status()
                        with open(local_file_path, 'wb') as f:
                            shutil.copyfileobj(r.raw, f)
                    self.logger.info(f"  Successfully downloaded '{filename}'.")
                    download_count += 1
                except requests.exceptions.RequestException as e:
                    self.logger.error(f"  Error downloading '{filename}': {e}")
                    if local_file_path.exists():
                        try:
                            os.remove(local_file_path)
                            self.logger.error(f"  Removed incomplete download: {filename}")
                        except OSError as remove_err:
                            self.logger.error(f"  Error removing incomplete download '{filename}': {remove_err}")
                except Exception as e:
                    self.logger.error(f"  An unexpected error occurred downloading '{filename}': {e}")

        self.logger.info(f"Downloaded {download_count} new/updated images.")

        # 4. Remove deleted images from local folder
        delete_count = 0
        for local_uid, local_path in local_files.items():
            if local_uid not in album_uids:
                self.logger.info(f"  Removing '{local_path.name}': no longer found in album.")
                try:
                    local_path.unlink()
                    delete_count += 1
                except OSError as e:
                    self.logger.error(f"  Error removing '{local_path.name}': {e}")
        self.logger.info(f"Removed {delete_count} deleted images from local folder.")
        self.logger.info("--- Sync complete ---")


# --- Main execution block with argparse ---
if __name__ == "__main__":
    service = PictureService()
    service.sync_images_to_folder()

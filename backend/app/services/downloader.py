import ipaddress
import mimetypes
import socket
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx


MAX_DOWNLOAD_SIZE = 1024 * 1024 * 1024
MAX_REDIRECTS = 5

ALLOWED_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".webm",
}


def validate_download_url(url: str) -> str:
    """Validate an authorized public HTTPS video URL."""

    parsed = urlparse(url.strip())

    if parsed.scheme != "https":
        raise ValueError("Only HTTPS download URLs are accepted.")

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid download URL.")

    hostname = parsed.hostname.lower()

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Local URLs are not allowed.")

    try:
        addresses = socket.getaddrinfo(
            hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Could not resolve download host.") from exc

    if not addresses:
        raise ValueError("Download host has no valid IP address.")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])

        if not ip.is_global:
            raise ValueError(
                "Private or non-public download hosts are not allowed."
            )

    return url.strip()


def _get_file_extension(url: str, content_type: str) -> str:
    path_extension = Path(urlparse(url).path).suffix.lower()

    if path_extension in ALLOWED_EXTENSIONS:
        return path_extension

    guessed_extension = mimetypes.guess_extension(
        content_type.split(";")[0].strip()
    )

    if guessed_extension in ALLOWED_EXTENSIONS:
        return guessed_extension

    return ".mp4"


def download_video(
    url: str,
    destination_dir: Path,
) -> Path:
    """
    Download an authorized direct HTTPS video into the
    caller-supplied video-specific directory.

    YouTube watch-page URLs are not supported.
    """

    destination_dir = Path(destination_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    current_url = validate_download_url(url)

    for redirect_number in range(MAX_REDIRECTS + 1):
        current_url = validate_download_url(current_url)

        with httpx.stream(
            "GET",
            current_url,
            follow_redirects=False,
            timeout=httpx.Timeout(30.0, read=120.0),
            trust_env=False,
        ) as response:

            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_number == MAX_REDIRECTS:
                    raise ValueError("Too many download redirects.")

                location = response.headers.get("location")

                if not location:
                    raise ValueError("Invalid redirect response.")

                current_url = urljoin(current_url, location)
                continue

            response.raise_for_status()

            content_type = response.headers.get(
                "content-type", ""
            ).lower()

            if not (
                content_type.startswith("video/")
                or "application/octet-stream" in content_type
            ):
                raise ValueError(
                    f"URL did not return a video file: {content_type}"
                )

            content_length = response.headers.get("content-length")

            if content_length:
                try:
                    if int(content_length) > MAX_DOWNLOAD_SIZE:
                        raise ValueError(
                            "Video exceeds the 1 GB download limit."
                        )
                except ValueError as error:
                    if "1 GB" in str(error):
                        raise
                    raise ValueError(
                        "Invalid download content length."
                    ) from error

            extension = _get_file_extension(
                current_url,
                content_type,
            )

            destination = (
                destination_dir / f"{uuid.uuid4().hex}{extension}"
            )

            downloaded = 0

            try:
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes(
                        chunk_size=1024 * 1024
                    ):
                        if not chunk:
                            continue

                        downloaded += len(chunk)

                        if downloaded > MAX_DOWNLOAD_SIZE:
                            raise ValueError(
                                "Video exceeds the 1 GB download limit."
                            )

                        output.write(chunk)

                if downloaded == 0:
                    raise ValueError("Downloaded file is empty.")

                return destination

            except Exception:
                destination.unlink(missing_ok=True)
                raise

    raise ValueError("Could not download the video.")

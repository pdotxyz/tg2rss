
#!/usr/bin/env python3

# ///
# requires-python = ">=3.9"
# dependencies = ["requests", "beautifulsoup4", "feedgen"]
# ///

"""tg2rss: turn public Telegram channels into RSS feeds, one <channel>.xml per channel.

HOW TO USE

1. Install uv:
       brew install uv

2. List your channels in channels.txt, one username per line.
   Example: https://t.me/durov -> durov

3. Run:
       uv run tg2rss.py durov
       uv run tg2rss.py $(cat channels.txt)

   One XML file is generated per channel.

4. Publish:
   GitHub Actions can run this script hourly and publish the XML files
   through GitHub Pages.

LIMITS

- Public Telegram channels only.
- Each run sees approximately the latest 20 posts.
- Photo posts are included, including posts with no caption.
- Images are embedded using their original Telegram image URLs.
- Images are not downloaded or hosted by this script.
- Video content is not embedded; only photo images are handled.
- Some Telegram posts may not expose their images in the public HTML.
"""

import argparse
import html
import re
import sys

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator


POST_TEXT = (
    ".tgme_widget_message_bubble > .tgme_widget_message_text, "
    ".media_supported_cont > .tgme_widget_message_text"
)

POST_TIME = ".tgme_widget_message_date time[datetime]"

# Telegram usually exposes photos as CSS background-image URLs.
PHOTO_SELECTOR = ".tgme_widget_message_photo_wrap"


def fetch_html(channel):
    response = requests.get(
        f"https://t.me/s/{channel}",
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.text


def extract_photo_urls(message):
    """Extract photo URLs from a Telegram post, including photo albums."""
    urls = []

    for photo in message.select(PHOTO_SELECTOR):
        style = photo.get("style", "")

        # Example:
        # background-image:url('https://cdn.../photo.jpg')
        matches = re.findall(
            r"background-image\s*:\s*url\(['\"]?(.*?)['\"]?\)",
            style,
            flags=re.IGNORECASE,
        )

        for url in matches:
            url = html.unescape(url.strip())

            if url.startswith(("https://", "http://")) and url not in urls:
                urls.append(url)

        # Fallback in case Telegram exposes an actual img element.
        for img in photo.select("img[src]"):
            url = html.unescape(img["src"].strip())

            if url.startswith(("https://", "http://")) and url not in urls:
                urls.append(url)

    return urls


def build_post_description(text, photo_urls):
    """Combine the original post HTML and images into RSS-compatible HTML."""
    parts = []

    if text:
        parts.append(str(text))

    for url in photo_urls:
        safe_url = html.escape(url, quote=True)

        parts.append(
            f'<p><img src="{safe_url}" '
            f'alt="Telegram post image" '
            f'style="max-width:100%;height:auto;" /></p>'
        )

    return "\n".join(parts)


def build_feed(channel, page_html):
    url = f"https://t.me/s/{channel}"

    feed = FeedGenerator()
    feed.title(channel)
    feed.link(href=url)
    feed.description(f"Posts from t.me/{channel}")

    soup = BeautifulSoup(page_html, "html.parser")

    for message in soup.select(".tgme_widget_message"):
        post = message.get("data-post")

        if not post:
            continue

        text = message.select_one(POST_TEXT)
        photo_urls = extract_photo_urls(message)

        # Keep text posts and photo-only posts.
        if not text and not photo_urls:
            continue

        entry = feed.add_entry()

        post_url = f"https://t.me/{post}"

        entry.id(post_url)
        entry.link(href=post_url)

        if text:
            title = text.get_text(" ", strip=True)[:80]
        else:
            title = "Photo post"

        entry.title(title)

        description = build_post_description(text, photo_urls)

        # description supports RSS readers that render HTML descriptions.
        entry.description(description)

        # content:encoded provides an additional HTML content field
        # for RSS readers that prefer it.
        entry.content(description, type="html")

        stamp = message.select_one(POST_TIME)

        if stamp:
            entry.pubDate(stamp["datetime"])

    # Keep lastBuildDate stable when the feed has not changed.
    dates = [
        entry.pubDate()
        for entry in feed.entry()
        if entry.pubDate()
    ]

    if dates:
        feed.lastBuildDate(max(dates))

    return feed


def channel_name(text):
    """Accept a bare Telegram username, without @ or a full URL."""
    if not re.fullmatch(r"\w+", text, re.ASCII):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a username. Type durov, not @durov or a t.me link"
        )

    return text


def update_feed(channel):
    """Fetch one channel and write <channel>.xml. Returns the number of posts."""
    feed = build_feed(channel, fetch_html(channel))

    if not feed.entry():
        raise ValueError(
            "no posts found (private channel, or web preview off?)"
        )

    feed.rss_file(f"{channel}.xml", pretty=True)

    return len(feed.entry())


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "channels",
        nargs="+",
        type=channel_name,
        metavar="channel",
        help="Telegram channel username, e.g. durov",
    )

    channels = parser.parse_args().channels

    failed = []

    for channel in channels:
        try:
            count = update_feed(channel)

        except Exception as error:
            failed.append(channel)
            print(
                f"{channel}: FAILED, old feed kept. {error}",
                file=sys.stderr,
            )

        else:
            print(
                f"{channel}: wrote {count} posts to {channel}.xml",
                flush=True,
            )

    if failed:
        sys.exit(
            f"{len(failed)} of {len(channels)} channel(s) failed: "
            f"{', '.join(failed)}"
        )


if __name__ == "__main__":
    main()

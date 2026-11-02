#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["requests", "beautifulsoup4", "feedgen"]
# ///
"""tg2rss: turn public Telegram channels into RSS feeds, one <channel>.xml per channel.

HOW TO USE
  No command line wanted? Skip steps 1-2 and go straight to 3A: it's all done on
  github.com in your browser, and GitHub installs everything itself.

  1. Set up (once, on your own computer)
     - Install uv. It reads the "dependencies" line at the top of tg2rss.py and
       installs those packages for you:
           brew install uv
       Prefer pip? pip install the packages from that line, then type "python3"
       instead of "uv run".
     - List your channels in channels.txt: one username per line, nothing else.
       The username is the part after t.me/ in the channel link (no @, no full link):
           https://t.me/durov  ->  durov

  2. Try it
           uv run tg2rss.py durov                  (one channel)
           uv run tg2rss.py $(cat channels.txt)    (every channel in channels.txt)
     You get one feed file per channel in the current folder (durov.xml, ...).
     Exit code: 0 = all OK, 1 = some channels failed (their old .xml is kept),
     2 = bad input (nothing ran). "uv run tg2rss.py --help" shows this guide.

  3. Publish the feeds. Pick ONE:

     A. Public URL, run by GitHub (for Blogtrottr, Feedly or your phone)
        Free for public repos, and no computer has to stay on. GitHub runs
        .github/workflows/tg2rss.yml every hour and only commits feeds that changed.
        All of this happens on github.com in your browser. Use your personal computer
        and account (not a work laptop). "Commit changes" is just GitHub's Save button.
        a. "+" (top right) -> "New repository" -> name it tg2rss -> Public -> tick
           "Add a README file" -> "Create repository". Free GitHub Pages needs a
           public repo, so anyone can see channels.txt and the feeds.
        b. "Add file" -> "Upload files" -> drag in tg2rss.py -> "Commit changes".
        c. "Add file" -> "Create new file" -> name it channels.txt -> type your
           usernames, one per line -> "Commit changes".
        d. "Add file" -> "Create new file" -> name it .github/workflows/tg2rss.yml
           (typing the "/" creates the folders) -> paste in the tg2rss.yml from this
           folder -> "Commit changes". Finder hides .github: press Cmd+Shift+. to see it.
        e. "Actions" tab -> "tg2rss" -> "Run workflow" -> "Run workflow". Wait a minute.
           Green tick = all good. Red cross = a channel failed (click the run to see
           which one); the feeds that worked are still published.
        f. "Settings" -> "Pages" -> "Deploy from a branch" -> main, /docs -> "Save".
        g. A minute later the feeds are live. Subscribe to each one in Blogtrottr:
               https://<github-username>.github.io/tg2rss/<channel>.xml
        Change channels later: open channels.txt on github.com, click the pencil, edit,
        "Commit changes". The next hourly run picks it up, or click "Run workflow".
        Removed a channel? Also delete docs/<channel>.xml ("..." menu -> "Delete file").
        Not needed on GitHub: test_tg2rss.py, .gitignore, .venv.

     B. Only on your Mac (for a reader on the same Mac, e.g. NetNewsWire)
        Keep this folder at ~/tg2rss: macOS blocks cron from Desktop, Documents
        and Downloads.
        a. Serve the folder to your own Mac only (keep this window open):
               cd ~/tg2rss && python3 -m http.server 8000 --bind 127.0.0.1
           Then subscribe to http://localhost:8000/durov.xml
        b. Refresh every hour with cron. Run "crontab -e" and add this line:
               0 * * * * cd ~/tg2rss && /full/path/to/uv run tg2rss.py $(cat channels.txt) >> tg2rss.log 2>&1
           Replace /full/path/to/uv with what "which uv" prints (cron doesn't know your PATH).

LIMITS
  - Public channels only. Invite links (t.me/+...) are private and won't work.
  - Each run sees the latest ~20 posts; your reader keeps the older ones.
  - Photo/video posts without a caption are skipped.
  - Needs a network that can reach t.me. The Walmart network blocks it.
  - GitHub pauses hourly jobs after 60 days with no repo activity. New posts count as
    activity, so this only happens if every channel goes quiet. Then click
    "Enable workflow" in the Actions tab.
"""
import argparse
import re
import sys

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# The post's own text, using the same selectors as RSSHub. The ">" (direct child)
# matters: a reply's quoted preview ALSO has class tgme_widget_message_text, and a
# plain ".tgme_widget_message_text" would grab that instead of the actual post.
POST_TEXT = (
    ".tgme_widget_message_bubble > .tgme_widget_message_text, "
    ".media_supported_cont > .tgme_widget_message_text"  # posts with media t.me can't show
)
POST_TIME = ".tgme_widget_message_date time[datetime]"


def fetch_html(channel):
    response = requests.get(f"https://t.me/s/{channel}", timeout=15)
    response.raise_for_status()
    return response.text


def build_feed(channel, html):
    url = f"https://t.me/s/{channel}"
    feed = FeedGenerator()
    fg.title(channel)
    feed.link(href=url)
    feed.description(f"Posts from t.me/{channel}")

    for message in BeautifulSoup(html, "html.parser").select(".tgme_widget_message"):
        post = message.get("data-post")
        text = message.select_one(POST_TEXT)
        if not post or not text:
            continue  # service messages and media-only posts have no text
        entry = feed.add_entry()  # prepends, so the newest post ends up on top
        entry.id(f"https://t.me/{post}")
        entry.link(href=f"https://t.me/{post}")
        entry.title(text.get_text(" ", strip=True)[:80])
        entry.description(str(text))
        stamp = message.select_one(POST_TIME)
        if stamp:
            entry.pubDate(stamp["datetime"])

    # feedgen stamps lastBuildDate with "now". Use the newest post instead, so an
    # unchanged channel gives a byte-identical file and GitHub has nothing to commit.
    dates = [entry.pubDate() for entry in feed.entry() if entry.pubDate()]
    if dates:
        feed.lastBuildDate(max(dates))
    return feed


def channel_name(text):
    """argparse type: a bare username like durov (no @, no link)."""
    if not re.fullmatch(r"\w+", text, re.ASCII):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a username. Type durov, not @durov or a t.me link")
    return text


def update_feed(channel):
    """Fetch one channel and write <channel>.xml. Returns the number of posts."""
    feed = build_feed(channel, fetch_html(channel))
    if not feed.entry():
        raise ValueError("no posts found (private channel, or web preview off?)")
    feed.rss_file(f"{channel}.xml", pretty=True)
    return len(feed.entry())


def main():
    # The how-to at the top of this file doubles as the --help text (one source of truth).
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("channels", nargs="+", type=channel_name, metavar="channel",
                        help="channel username, e.g. durov")
    channels = parser.parse_args().channels  # every name is checked before anything is fetched

    failed = []
    for channel in channels:
        try:
            count = update_feed(channel)
        except Exception as error:  # one broken channel must not stop the others
            failed.append(channel)
            print(f"{channel}: FAILED, old feed kept. {error}", file=sys.stderr)
        else:
            # flush: keeps log lines in order when cron sends both outputs to one file
            print(f"{channel}: wrote {count} posts to {channel}.xml", flush=True)
    if failed:
        sys.exit(f"{len(failed)} of {len(channels)} channel(s) failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()

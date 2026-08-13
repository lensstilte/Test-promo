import os
import random
import requests
from datetime import datetime, timezone


BLUESKY_BASE_URL = "https://bsky.social"


class BlueskyClient:
    def __init__(self, identifier: str, password: str):
        self.identifier = identifier
        self.password = password
        self.session = requests.Session()
        self.did = None
        self.access_jwt = None

    def login(self):
        url = f"{BLUESKY_BASE_URL}/xrpc/com.atproto.server.createSession"
        resp = self.session.post(
            url,
            json={"identifier": self.identifier, "password": self.password},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_jwt = data["accessJwt"]
        self.did = data["did"]
        self.session.headers.update({"Authorization": f"Bearer {self.access_jwt}"})

    def _get(self, path: str, params: dict | None = None):
        url = f"{BLUESKY_BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict):
        url = f"{BLUESKY_BASE_URL}{path}"
        resp = self.session.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_own_media_posts(self, max_posts: int = 200):
        """
        Haal eigen posts met images op (geen reposts).
        Returned lijst met dicts met uri, cid, createdAt.
        """
        posts: list[dict] = []
        cursor = None

        while len(posts) < max_posts:
            params = {
                "actor": self.identifier,
                "limit": 100,
                "filter": "posts_with_media",
            }
            if cursor:
                params["cursor"] = cursor

            data = self._get("/xrpc/app.bsky.feed.getAuthorFeed", params=params)
            feed = data.get("feed", [])

            for item in feed:
                # Skip reposts (feed items met "reason" zijn meestal reposts)
                if "reason" in item:
                    continue

                post = item.get("post")
                if not post:
                    continue

                # Extra check: alleen eigen DID
                author = post.get("author", {})
                if author.get("did") != self.did:
                    continue

                # Check of er überhaupt images inzitten
                embed = post.get("embed") or {}
                has_images = False

                if embed.get("$type") == "app.bsky.embed.images#view":
                    has_images = True
                elif embed.get("$type") == "app.bsky.embed.recordWithMedia#view":
                    media = embed.get("media") or {}
                    if media.get("$type") == "app.bsky.embed.images#view":
                        has_images = True

                if not has_images:
                    continue

                record = post.get("record", {})
                created_at = record.get("createdAt") or post.get("indexedAt")
                if not created_at:
                    continue

                posts.append(
                    {
                        "uri": post["uri"],
                        "cid": post["cid"],
                        "createdAt": created_at,
                    }
                )

                if len(posts) >= max_posts:
                    break

            cursor = data.get("cursor")
            if not cursor:
                break

        return posts

    def get_repost_uri_for_post(self, uri: str) -> str | None:
        """
        Kijkt of WIJ deze post al eens gerepost hebben.
        Als ja, dan zit er in viewer.repost een uri van onze repost-record.
        """
        data = self._get("/xrpc/app.bsky.feed.getPosts", params={"uris": uri})
        posts = data.get("posts", [])
        if not posts:
            return None

        viewer = posts[0].get("viewer") or {}
        return viewer.get("repost")

    def delete_repost_by_uri(self, repost_uri: str):
        """
        Verwijder een bestaande repost-record (unrepost).
        """
        if not repost_uri:
            return

        rkey = repost_uri.split("/")[-1]
        payload = {
            "repo": self.did,
            "collection": "app.bsky.feed.repost",
            "rkey": rkey,
        }
        self._post("/xrpc/com.atproto.repo.deleteRecord", payload)

    def create_repost(self, subject_uri: str, subject_cid: str):
        """
        Maak een nieuwe repost-record aan.
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "repo": self.did,
            "collection": "app.bsky.feed.repost",
            "record": {
                "$type": "app.bsky.feed.repost",
                "subject": {"uri": subject_uri, "cid": subject_cid},
                "createdAt": now,
            },
        }
        self._post("/xrpc/com.atproto.repo.createRecord", payload)

    def ensure_fresh_repost(self, subject_uri: str, subject_cid: str):
        """
        Zorgt dat we eerst de oude repost verwijderen (alleen als die bestaat),
        en dan opnieuw repost doen.
        """
        existing_repost_uri = self.get_repost_uri_for_post(subject_uri)
        if existing_repost_uri:
            # Alleen de repost van deze post verwijderen
            self.delete_repost_by_uri(existing_repost_uri)

        # Daarna opnieuw repost
        self.create_repost(subject_uri, subject_cid)


def parse_iso(dt: str) -> datetime:
    # Bluesky timestamps zijn meestal ISO8601 met 'Z' op het eind
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


def main():
    username = os.environ.get("BSKY_USERNAME")
    password = os.environ.get("BSKY_PASSWORD")

    if not username or not password:
        raise RuntimeError("BSKY_USERNAME en/of BSKY_PASSWORD ontbreken in de env vars.")

    client = BlueskyClient(username, password)
    client.login()

    # 1) Alle eigen foto-posts ophalen (geen reposts)
    posts = client.get_own_media_posts(max_posts=200)
    if not posts:
        return

    # 2) Sorteren op createdAt (oud -> nieuw)
    posts_sorted = sorted(posts, key=lambda p: parse_iso(p["createdAt"]))

    # Alleen de nieuwste 3 posts
    newest_3 = posts_sorted[-3:]

    # Oud -> nieuw reposten, zodat de nieuwste als laatste wordt gerepost
    # en daardoor bovenaan eindigt
    for post in newest_3:
        uri = post["uri"]
        cid = post["cid"]

        try:
            client.ensure_fresh_repost(uri, cid)
        except Exception:
            continue


if __name__ == "__main__":
    main()

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

    # Als er minder dan 10 posts zijn, gewoon zoveel mogelijk doen
    newest_10 = posts_sorted[-10:] if len(posts_sorted) >= 10 else posts_sorted[:]
    older_pool = posts_sorted[:-10] if len(posts_sorted) > 10 else []

    # 10 random oude posts (als er minder zijn, dan zoveel als er zijn)
    if older_pool:
        if len(older_pool) > 10:
            old_random = random.sample(older_pool, 10)
        else:
            old_random = older_pool[:]
        random.shuffle(old_random)  # random volgorde oude posts
    else:
        old_random = []

    # Nieuwste 10 van oud -> nieuw (dus zoals posts_sorted al is)
    newest_10_sorted = sorted(newest_10, key=lambda p: parse_iso(p["createdAt"]))

    # Volgorde:
    # 1. 10 random oude
    # 2. nieuwsten 10 van oud -> nieuw (zodat de aller-nieuwste als laatste bovenaan komt)
    final_sequence = old_random + newest_10_sorted

    # Alleen maximaal 20 reposts per run (10 oud + 10 nieuw)
    final_sequence = final_sequence[:20]

    for post in final_sequence:
        uri = post["uri"]
        cid = post["cid"]
        try:
            client.ensure_fresh_repost(uri, cid)
        except Exception:
            # Geen logging/boekhouding bijhouden, dus fouten gewoon negeren
            continue


if __name__ == "__main__":
    main()

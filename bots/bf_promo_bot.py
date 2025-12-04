import os
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from atproto import Client


# -----------------------------------
# INSTELLINGEN
# -----------------------------------

# BF promo feed
FEED_NAME = "BF promo"
FEED_URI = "at://did:plc:jaka644beit3x4vmmg6yysw7/app.bsky.feed.generator/aaaolr5sgy35a"

# Logbestand voor repost cooldown (geldt voor alle reposts)
REPOST_LOG_FILE = "bf_promo_repost_log.json"
COOLDOWN_DAYS = 14  # 2 weken

# Account waarvan we followers willen tonen in de stats-reply
STATS_ACCOUNT_HANDLE = "nakedneighbour1985.bsky.social"

# Bestanden voor optionele 2e repost-account (nu nog niet actief)
REPOST2_STATE_FILE = "repost2_last_reposts.json"

# Quote-account tekst instellingen (voor @hotbleusky)
TITLE = "🔥𝐧𝐚𝐤𝐞𝐝𝐧𝐞𝐢𝐠𝐡𝐛𝐨𝐮𝐫𝟏𝟗𝟖5🔥"
LINK = "https://onlyfans.com/ericalaurenxxovip"
HASHTAGS = [
    "#bskypromo", "#realnsfw", "#girlswithtattoos", "#tattooedgirl", "#tattoo",
    "#bigtits", "#busty", "#curvy", "#boobs", "#boobies", "#tits", "#milf",
    "#realmilf", "#of", "#hotmom", "#realgirls", "#curvy", "#nsfw",
    "#skyhub", "#spicysky", "#onlyfans",
]
TAGLINE = "Follow for more spicy mom content 🔥\n@nakedneighbour1985.bsky.social"


# -----------------------------------
# HULPFUNCTIES: JSON
# -----------------------------------

def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -----------------------------------
# HULPFUNCTIES: REPOST LOG (COOLDOWN)
# -----------------------------------

def load_repost_log() -> Dict[str, str]:
    """
    Laadt log {uri: iso_timestamp} en gooit entries weg ouder dan de cooldown.
    """
    data: Dict[str, str] = load_json(REPOST_LOG_FILE, {})
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=COOLDOWN_DAYS)

    cleaned: Dict[str, str] = {}
    for uri, ts in data.items():
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if dt >= cutoff:
            cleaned[uri] = ts

    if cleaned != data:
        save_json(REPOST_LOG_FILE, cleaned)

    return cleaned


def can_repost(uri: str, log: Dict[str, str]) -> bool:
    """True als deze post niet in de laatste 14 dagen gerepost is."""
    return uri not in log


def mark_reposted(uri: str, log: Dict[str, str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    log[uri] = now
    save_json(REPOST_LOG_FILE, log)


# -----------------------------------
# HULPFUNCTIES: LOGIN
# -----------------------------------

def login_client(username_env: str, password_env: str) -> Client:
    username = os.getenv(username_env)
    password = os.getenv(password_env)
    if not username or not password:
        raise RuntimeError(f"Missing {username_env} or {password_env}")
    client = Client()
    client.login(username, password)
    print(f"🔐 Ingelogd als {client.me.handle} via {username_env}")
    return client


# -----------------------------------
# HULPFUNCTIES: FEED & POSTS
# -----------------------------------

def get_feed_posts(client: Client):
    """
    Haalt de feed op en retourneert alle items met een 'post'.
    Geen strenge type-filter meer, zodat generator-feeds ook werken.
    """
    print("=== [1/6] Feed ophalen ===")
    resp = client.app.bsky.feed.get_feed({"feed": FEED_URI, "limit": 50})
    items = resp.feed

    posts = []
    for item in items:
        post = getattr(item, "post", None)
        if post is None:
            continue
        posts.append(item)

    print(f"📂 Aantal posts in feed (na filter): {len(posts)}")
    return posts


# -----------------------------------
# HULPFUNCTIES: SOCIAL ACTIONS (FOLLOW / LIKE / REPOST / QUOTE)
# -----------------------------------

def ensure_follow(client: Client, actor_did: str, actor_handle: str) -> None:
    """Volg de auteur als je die nog niet volgt."""
    try:
        profile = client.app.bsky.actor.get_profile({"actor": actor_did})
    except Exception as e:
        print(f"⚠️ Kon profiel niet ophalen voor {actor_handle}: {e}")
        return

    viewer = getattr(profile, "viewer", None)
    already_following = bool(viewer and getattr(viewer, "following", None))

    if already_following:
        print(f"✔️ Je volgt {actor_handle} al.")
        return

    try:
        print(f"➕ Volgen: {actor_handle}")
        client.follow(actor_did)
        print("✔️ Gevolgd.")
    except Exception as e:
        print(f"⚠️ Kon {actor_handle} niet volgen: {e}")


def repost_post(client: Client, uri: str, cid: str, reason: str = "") -> bool:
    """Repost met duidelijke output. Returns True als het gelukt is."""
    try:
        print(f"🔁 Reposting ({reason}): {uri}")
        client.repost(uri, cid)
        print("✔️ Repost gelukt.")
        return True
    except Exception as e:
        print(f"⚠️ Repost mislukt ({reason}): {e}")
        return False


def like_post(client: Client, uri: str, cid: Optional[str] = None) -> None:
    """Like de post als dat nog niet is gedaan."""
    try:
        print(f"❤️ Like geven op: {uri}")
        if cid is not None:
            client.like(uri, cid)
        else:
            client.like(uri)
    except Exception as e:
        print(f"⚠️ Like mislukt: {e}")


def follow_likers(client: Client, post_uri: str) -> int:
    """
    Volgt automatisch likers met profielfoto en geen 'lege' accounts
    (0 posts, 0 volgers, 0 following).
    Geeft terug hoeveel nieuwe mensen zijn gevolgd.
    """
    print(f"=== [4/x] Likers volgen voor post ===")
    print(f"👥 Likers ophalen van post: {post_uri}")

    try:
        likes_resp = client.app.bsky.feed.get_likes({"uri": post_uri})
    except Exception as e:
        print(f"⚠️ Kon likes niet ophalen: {e}")
        return 0

    likes = getattr(likes_resp, "likes", [])
    if not likes:
        print("ℹ️ Geen likers gevonden.")
        return 0

    me = client.me
    followed_count = 0

    for like in likes:
        actor = like.actor
        did = actor.did
        handle = actor.handle

        # sla jezelf over
        if did == me.did:
            continue

        # profiel ophalen
        try:
            profile = client.app.bsky.actor.get_profile({"actor": did})
        except Exception:
            continue

        # ✅ alleen accounts met avatar
        if not getattr(profile, "avatar", None):
            print(f"⛔ Geen profielfoto → overslaan: {handle}")
            continue

        # ✅ 'leeg' = 0 posts, 0 volgers, 0 following
        posts_count = getattr(profile, "postsCount", 0)
        followers_count = getattr(profile, "followersCount", 0)
        follows_count = getattr(profile, "followsCount", 0)

        is_empty = (
            posts_count == 0 and
            followers_count == 0 and
            follows_count == 0
        )

        if is_empty:
            print(f"⛔ Leeg account (0 posts/0 volgers/0 following) → overslaan: {handle}")
            continue

        # al volgen?
        viewer = getattr(profile, "viewer", None)
        already_following = bool(viewer and getattr(viewer, "following", None))

        if already_following:
            continue

        print(f"➕ Likers-volg (avatar & niet leeg): {handle}")
        try:
            client.follow(did)
            followed_count += 1
        except Exception as e:
            print(f"⚠️ Kon liker niet volgen ({handle}): {e}")

    print(f"📊 Deze run {followed_count} nieuwe mensen gevolgd via likes voor deze post.")
    return followed_count


def reply_with_stats(bot_client: Client, parent_uri: str, parent_cid: str) -> None:
    """
    Plaats een reply onder de gegeven post met stats van @nakedneighbour1985.bsky.social
    + likes/reposts van deze post.
    """
    print("=== [5/x] Stats-reply plaatsen ===")

    # 1) profiel van stats-account
    followers = 0
    try:
        profile = bot_client.app.bsky.actor.get_profile({"actor": STATS_ACCOUNT_HANDLE})
        followers = getattr(profile, "followersCount", 0) or 0
    except Exception as e:
        print(f"⚠️ Kon stats-profiel niet ophalen ({STATS_ACCOUNT_HANDLE}): {e}")

    # 2) likes van deze post
    try:
        likes_resp = bot_client.app.bsky.feed.get_likes({"uri": parent_uri})
        likes_count = len(getattr(likes_resp, "likes", []))
    except Exception as e:
        print(f"⚠️ Kon likes niet ophalen (stats): {e}")
        likes_count = 0

    # 3) reposts van deze post
    try:
        reposts_resp = bot_client.app.bsky.feed.get_reposted_by({"uri": parent_uri})
        reposts_count = len(getattr(reposts_resp, "repostedBy", []))
    except Exception as e:
        print(f"⚠️ Kon reposts niet ophalen (stats): {e}")
        reposts_count = 0

    text = (
        "Volgers, reposts, likes\n"
        f"{followers}-{reposts_count}-{likes_count}"
    )

    print(f"💬 Reply met stats plaatsen onder: {parent_uri}")
    try:
        # gebruik high-level helper send_post met reply_to
        bot_client.send_post(
            text=text,
            reply_to={
                "uri": parent_uri,
                "cid": parent_cid,
            },
        )
        print("✔️ Reply met stats geplaatst.")
    except Exception as e:
        print(f"⚠️ Fout bij plaatsen stats-reply: {e}")


def quote_post(quote_client: Optional[Client], target_uri: str, target_cid: str) -> None:
    """
    Maakt een citaatpost op het quote-account (@hotbleusky)
    met vaste titel, link, hashtags en tagline.
    """
    if quote_client is None:
        return

    print("=== [6/x] Citaatpost op quote-account ===")

    text = (
        f"{TITLE}\n\n"
        f"{LINK}\n\n"
        + " ".join(HASHTAGS)
        + "\n\n"
        + TAGLINE
    )

    print(f"💬 Citaatpost maken voor: {target_uri}")
    try:
        quote_client.post(
            text=text,
            embed={
                "$type": "app.bsky.embed.record",
                "record": {
                    "uri": target_uri,
                    "cid": target_cid,
                },
            },
        )
        print("✔️ Citaatpost geplaatst.")
    except Exception as e:
        print(f"⚠️ Fout bij citaatpost: {e}")


# -----------------------------------
# HOOFDFUNCTIE
# -----------------------------------

def main():
    print("========================================")
    print(f"🚀 BF Promo Bot start – feed: {FEED_NAME}")
    print(f"📎 Feed URI: {FEED_URI}")
    print("========================================")

    # 1) Login: hoofdaccount (@beautyfan)
    try:
        bot_client = login_client("BSKY_USERNAME", "BSKY_PASSWORD")
    except RuntimeError as e:
        print(f"❌ Kan hoofdaccount niet inloggen: {e}")
        return

    # 2) Login: quote-account (@hotbleusky)
    quote_client: Optional[Client] = None   0
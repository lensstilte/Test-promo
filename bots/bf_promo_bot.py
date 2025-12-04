import os
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from atproto import Client

# -----------------------------------
# INSTELLINGEN
# -----------------------------------

# Doel-account (samenwerking): hier halen we ALLE posts vandaan
TARGET_HANDLE = "nakedneighbour1985.bsky.social"

# Logbestand voor repost cooldown (geldt alleen voor oude posts)
REPOST_LOG_FILE = "bf_promo_repost_log.json"
COOLDOWN_DAYS = 14  # 2 weken


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
    Geldt alleen voor oude posts, niet voor de nieuwste.
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
    """True als deze (oude) post niet in de laatste 14 dagen gerepost is."""
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
    return client


# -----------------------------------
# HULPFUNCTIES: POSTS
# -----------------------------------

def get_author_posts(client: Client, target_did: str, limit: int = 50):
    """
    Haalt de author-feed op van het samenwerkingsaccount.
    We vertrouwen op de volgorde van de API: NIEUWSTE eerst.
    """
    print("=== [1/4] Auteur-feed ophalen ===")
    resp = client.app.bsky.feed.get_author_feed(
        {"actor": target_did, "limit": limit}
    )
    items = resp.feed

    posts = []
    for item in items:
        post = getattr(item, "post", None)
        if post is None:
            continue
        posts.append(item)

    print(f"📂 Aantal posts in auteur-feed: {len(posts)}")
    return posts


# -----------------------------------
# HULPFUNCTIES: SOCIAL ACTIONS
# -----------------------------------

def ensure_follow(client: Client, actor_did: str) -> None:
    """Volg de auteur als je die nog niet volgt (zonder namen te loggen)."""
    try:
        profile = client.app.bsky.actor.get_profile({"actor": actor_did})
    except Exception as e:
        print(f"⚠️ Kon profiel niet ophalen voor account (privacy): {e}")
        return

    viewer = getattr(profile, "viewer", None)
    already_following = bool(viewer and getattr(viewer, "following", None))

    if already_following:
        print("✔️ Auteur wordt al gevolgd.")
        return

    try:
        print("➕ Auteur volgen.")
        client.follow(actor_did)
        print("✔️ Auteur gevolgd.")
    except Exception as e:
        print(f"⚠️ Kon auteur niet volgen: {e}")


def repost_post(client: Client, uri: str, cid: str, reason: str = "") -> bool:
    """Repost met duidelijke output. Returns True als het gelukt is."""
    try:
        if reason:
            print(f"🔁 Reposting ({reason}).")
        else:
            print("🔁 Reposting.")
        # Puur repost, GEEN tekst
        client.repost(uri, cid)
        print("✔️ Repost gelukt.")
        return True
    except Exception as e:
        print(f"⚠️ Repost mislukt: {e}")
        return False


def like_post(client: Client, uri: str, cid: Optional[str] = None) -> None:
    """Like de post als dat nog niet is gedaan."""
    try:
        print("❤️ Like geven op geselecteerde post.")
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
    Geen accountnamen in de logs, alleen aantallen.
    Geeft terug hoeveel nieuwe mensen zijn gevolgd.
    """
    print("=== [x] Likers volgen voor post ===")
    print("👥 Likers ophalen voor geselecteerde post...")

    try:
        likes_resp = client.app.bsky.feed.get_likes({"uri": post_uri})
    except Exception as e:
        print(f"⚠️ Kon likes niet ophalen: {e}")
        return 0

    likes = getattr(likes_resp, "likes", [])
    total_likers = len(likes)
    if not likes:
        print("ℹ️ Geen likers gevonden.")
        return 0

    me = client.me
    followed_count = 0
    skipped_empty = 0
    skipped_no_avatar = 0
    skipped_already = 0
    skipped_other = 0

    for like in likes:
        actor = like.actor
        did = actor.did

        # sla jezelf over
        if did == me.did:
            skipped_other += 1
            continue

        # profiel ophalen
        try:
            profile = client.app.bsky.actor.get_profile({"actor": did})
        except Exception:
            skipped_other += 1
            continue

        # ✅ alleen accounts met avatar
        if not getattr(profile, "avatar", None):
            skipped_no_avatar += 1
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
            skipped_empty += 1
            continue

        # al volgen?
        viewer = getattr(profile, "viewer", None)
        already_following = bool(viewer and getattr(viewer, "following", None))

        if already_following:
            skipped_already += 1
            continue

        try:
            client.follow(did)
            followed_count += 1
        except Exception as e:
            print(f"⚠️ Kon liker niet volgen (privacy): {e}")
            skipped_other += 1

    print(f"👥 Totaal likers gevonden: {total_likers}")
    print(f"⛔ Overgeslagen (geen avatar): {skipped_no_avatar}")
    print(f"⛔ Overgeslagen (leeg account): {skipped_empty}")
    print(f"⛔ Overgeslagen (al gevolgd / anders): {skipped_already + skipped_other}")
    print(f"📊 Nieuwe accounts gevolgd via likes: {followed_count}")

    return followed_count


def unrepost_if_needed(client: Client, post_obj, is_newest: bool) -> None:
    """
    Voor de nieuwste post:
    als er al een repost bestaat vanaf dit account, haal die eerst weg
    zodat de nieuwe repost weer bovenaan komt te staan.
    """
    if not is_newest:
        return

    viewer = getattr(post_obj, "viewer", None)
    if not viewer:
        return

    existing_repost = getattr(viewer, "repost", None)
    if not existing_repost:
        return

    # existing_repost kan een string of een object met .uri zijn
    if isinstance(existing_repost, str):
        repost_uri = existing_repost
    else:
        repost_uri = getattr(existing_repost, "uri", None)

    if not repost_uri:
        return

    print("🔄 Nieuwste post is al gerepost, oude repost verwijderen...")
    try:
        client.unrepost(repost_uri)
        print("✔️ Oude repost verwijderd.")
    except Exception as e:
        print(f"⚠️ Kon oude repost niet verwijderen: {e}")


# -----------------------------------
# HOOFDFUNCTIE
# -----------------------------------

def main():
    print("========================================")
    print("🚀 BF Promo Bot start – op basis van account-feed")
    print(f"🎯 Doel-account: {TARGET_HANDLE}")
    print("========================================")

    # 1) Login: hoofdaccount (bijv. @beautyfan)
    try:
        bot_client = login_client("BSKY_USERNAME", "BSKY_PASSWORD")
        print("🔐 Hoofdaccount ingelogd.")
    except RuntimeError as e:
        print(f"❌ Kan hoofdaccount niet inloggen: {e}")
        return

    # 2) Login: 2e repost-account (bijv. @hotbleusky) – zelfde gedrag als hoofdaccount
    second_client: Optional[Client] = None
    try:
        second_client = login_client("QUOTE_BSKY_USERNAME", "QUOTE_BSKY_PASSWORD")
        print("🔐 2e repost-account ingelogd.")
    except RuntimeError:
        print("ℹ️ 2e repost-account niet geactiveerd (QUOTE_BSKY_* secrets ontbreken).")

    # 3) DID van doel-account ophalen
    try:
        profile = bot_client.app.bsky.actor.get_profile({"actor": TARGET_HANDLE})
        target_did = profile.did
        print("🎯 Doel-account profiel opgehaald.")
    except Exception as e:
        print(f"❌ Kan doel-account niet ophalen: {e}")
        return

    # 4) Repost-log laden (cooldown 14 dagen, alleen voor oude posts)
    repost_log = load_repost_log()
    print(f"🧠 Repost-log geladen (entries na cleanup): {len(repost_log)}")

    # 5) Auteur-feed ophalen (NIEUWSTE eerst)
    posts = get_author_posts(bot_client, target_did, limit=50)
    if not posts:
        print("ℹ️ Geen posts in auteur-feed – stoppen.")
        return

    me = bot_client.me

    # Filter posts die niet van jezelf zijn (veiligheid)
    external_posts = [item for item in posts if item.post.author.did != me.did]
    if not external_posts:
        print("ℹ️ Geen externe posts (alleen eigen posts) – stoppen.")
        return

    # Nieuwste post = eerste item van de auteur-feed
    newest_item = external_posts[0]
    newest_uri = newest_item.post.uri
    newest_post = newest_item.post

    # Debug: toon timestamp van nieuwste post
    record = getattr(newest_post, "record", None)
    created_at = getattr(record, "createdAt", None)
    indexed_at = getattr(newest_post, "indexedAt", None)
    print(f"🕒 Nieuwste post timestamp (createdAt / indexedAt): {created_at} / {indexed_at}")

    # Oude posts = rest
    older_items = external_posts[1:]

    # Filter voor oude posts (cooldown, geen eigen posts)
    old_candidates = []
    for item in older_items:
        uri = item.post.uri
        if not can_repost(uri, repost_log):
            continue
        old_candidates.append(item)

    print(f"📊 Oude kandidaten (na cooldown): {len(old_candidates)}")
    print("📊 Nieuwste post kan worden gebruikt (is geen eigen post).")

    # kies max 2 willekeurige oude posts
    chosen_old: List = []
    if old_candidates:
        chosen_old = random.sample(old_candidates, min(2, len(old_candidates)))

    # volgorde: eerst 2 oude posts, dan nieuwste (zodat nieuwste bovenaan komt)
    selected_items: List = []
    selected_items.extend(chosen_old)
    selected_items.append(newest_item)  # altijd de nieuwste erbij

    print(f"✅ Totaal geselecteerde posts deze run: {len(selected_items)}")

    # -----------------------------------
    # UITVOERING VOOR ELKE GEKOZEN POST
    # -----------------------------------

    total_followed = 0
    index = 0

    for item in selected_items:
        index += 1
        post = item.post
        uri = post.uri
        cid = post.cid
        author = post.author

        is_newest = (uri == newest_uri)
        reason = "nieuwste post" if is_newest else "random oude"

        print("----------------------------------------")
        print(f"▶️ [{index}/{len(selected_items)}] Verwerken: {reason}")
        print(f"   Post URI: {uri}")

        # 1) Auteur volgen op hoofdaccount
        ensure_follow(bot_client, author.did)

        # 2) Als dit de nieuwste is: oude repost (indien aanwezig) eerst verwijderen
        unrepost_if_needed(bot_client, post, is_newest=is_newest)

        # 3) Repost op hoofdaccount
        print("=== [2/4] Repost hoofdaccount ===")
        if not repost_post(bot_client, uri, cid, reason=reason):
            continue

        # 4) Like op hoofdaccount
        print("=== [3/4] Like hoofdaccount ===")
        like_post(bot_client, uri, cid)

        # 5) Likers volgen via hoofdaccount
        followed_now = follow_likers(bot_client, uri)
        total_followed += followed_now

        # 6) 2e repost-account: zelfde gedrag, maar zonder unrepost-logica
        if second_client is not None:
            print("=== [4/4] Repost 2e account ===")
            ensure_follow(second_client, author.did)
            repost_post(second_client, uri, cid, reason=reason)
            like_post(second_client, uri, cid)

        # 7) Oude posts in cooldown-log, nieuwste niet
        if not is_newest:
            mark_reposted(uri, repost_log)

    print("========================================")
    print(f"📈 Nieuwe accounts gevolgd via likes (alle posts): {total_followed}")
    print("✅ BF Promo Bot run afgerond.")
    print("========================================")


if __name__ == "__main__":
    main()
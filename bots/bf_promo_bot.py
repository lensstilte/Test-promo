
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

# Logbestand voor repost cooldown (geldt alleen voor oude posts)
REPOST_LOG_FILE = "bf_promo_repost_log.json"
COOLDOWN_DAYS = 14  # 2 weken

# Account waarmee je samenwerkt / waarvan je stats wilt tonen
STATS_ACCOUNT_HANDLE = "nakedneighbour1985.bsky.social"

# (optioneel) 2e repost-account state file (nog niet actief gebruikt)
REPOST2_STATE_FILE = "repost2_last_reposts.json"

# Quote-account tekst instellingen (voor @hotbleusky)
TITLE = "🔥𝐧𝐚𝐤𝐞𝐝𝐧𝐞𝐢𝐠𝐡𝐛𝐨𝐮𝐫𝟏𝟗𝟖5🔥"
LINK = "https://onlyfans.com/ericalaurenxxovip"
HASHTAGS = [
    "#bskypromo", "#realnsfw", "#girlswithtattoos", "#tattooedgirl", "#tattoo",
    "#bigtits", "#busty", "#curvy", "#boobs", "#boobies", "#tits", "#milf",
    "#realmilf", "#of", "#hotmom", "#realgirls", "#nsfw",
    "#skyhub", "#spicysky", "#onlyfans",
]
TAGLINE = "follow for more🔥"


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
# HULPFUNCTIES: FEED & POSTS
# -----------------------------------

def get_feed_posts(client: Client):
    """
    Haalt de feed op en retourneert alle items met een 'post'.
    Geen strenge type-filter, zodat generator-feeds ook werken.
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


def get_post_timestamp(item) -> str:
    """
    Haal timestamp string voor sortering (oud -> nieuw), op basis van post-datum.
    We gebruiken hier alleen record.createdAt van de originele post.
    """
    record = getattr(item.post, "record", None)
    ts = getattr(record, "createdAt", "")
    return ts or ""


# -----------------------------------
# HULPFUNCTIES: SOCIAL ACTIONS (FOLLOW / LIKE / REPOST / QUOTE)
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
        # LET OP: echte repost, GEEN tekst
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
    print("=== [4/x] Likers volgen voor post ===")
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


def reply_with_stats(bot_client: Client, parent_uri: str, parent_cid: str) -> None:
    """
    Plaats een reply onder de gegeven post met stats van STATS_ACCOUNT_HANDLE
    + likes/reposts van deze post.
    """
    print("=== [5/x] Stats-reply plaatsen ===")

    # 1) profiel van stats-account
    followers = 0
    try:
        profile = bot_client.app.bsky.actor.get_profile({"actor": STATS_ACCOUNT_HANDLE})
        followers = getattr(profile, "followersCount", 0) or 0
    except Exception as e:
        print(f"⚠️ Kon stats-profiel niet volledig ophalen (privacy): {e}")

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

    print("💬 Stats-reply record aanmaken...")

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reply": {
            "root": {"uri": parent_uri, "cid": parent_cid},
            "parent": {"uri": parent_uri, "cid": parent_cid},
        },
    }

    try:
        bot_client.com.atproto.repo.create_record(
            {
                "repo": bot_client.me.did,
                "collection": "app.bsky.feed.post",
                "record": record,
            }
        )
        print("✔️ Reply met stats geplaatst.")
    except Exception as e:
        print(f"⚠️ Fout bij plaatsen stats-reply (create_record): {e}")


def quote_post(quote_client: Optional[Client], target_uri: str, target_cid: str) -> None:
    """
    Maakt een citaatpost op het quote-account (@hotbleusky)
    met vaste titel, link, hashtags en tagline.
    """
    if quote_client is None:
        return

    print("=== [6/x] Citaatpost op quote-account ===")

    # Bouw een compacte tekst, bewust kort
    base_text = (
        f"{TITLE}\n"
        f"{LINK}\n"
        + " ".join(HASHTAGS[:15])  # max 15 hashtags
        + f"\n{TAGLINE}"
    )

    # Bluesky limiet ~300 graphemes → veiligheidsmarge
    MAX_LEN = 280
    if len(base_text) > MAX_LEN:
        text = base_text[: MAX_LEN - 3] + "..."
    else:
        text = base_text

    print("💬 Citaatpost aanmaken...")
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
    print(f"🚀 BF Promo Bot start – feed: {FEED_NAME}")
    print(f"📎 Feed URI: {FEED_URI}")
    print("========================================")

    # 1) Login: hoofdaccount (@beautyfan)
    try:
        bot_client = login_client("BSKY_USERNAME", "BSKY_PASSWORD")
        print("🔐 Hoofdaccount ingelogd.")
    except RuntimeError as e:
        print(f"❌ Kan hoofdaccount niet inloggen: {e}")
        return

    # 2) Login: quote-account (@hotbleusky)
    quote_client: Optional[Client] = None
    try:
        quote_client = login_client("QUOTE_BSKY_USERNAME", "QUOTE_BSKY_PASSWORD")
        print("🔐 Quote-account ingelogd.")
    except RuntimeError:
        print("ℹ️ Quote-account niet geactiveerd (QUOTE_BSKY_* secrets ontbreken).")

    # 3) (optioneel) 2e repost-account – nog niet actief in logica
    repost2_client: Optional[Client] = None
    try:
        repost2_client = login_client("REPOST2_BSKY_USERNAME", "REPOST2_BSKY_PASSWORD")
        print("ℹ️ 2e repost-account is ingelogd, maar logica is nog niet actief in deze versie.")
    except RuntimeError:
        print("ℹ️ 2e repost-account niet geactiveerd (REPOST2_BSKY_* secrets ontbreken).")

    # 4) Repost-log laden (cooldown 14 dagen, alleen voor oude posts)
    repost_log = load_repost_log()
    print(f"🧠 Repost-log geladen (entries na cleanup): {len(repost_log)}")

    # 5) Feed ophalen
    posts = get_feed_posts(bot_client)
    if not posts:
        print("ℹ️ Geen posts in feed – stoppen.")
        return

    # 6) DID van samenwerking-account ophalen
    target_did: Optional[str] = None
    try:
        profile = bot_client.app.bsky.actor.get_profile({"actor": STATS_ACCOUNT_HANDLE})
        target_did = profile.did
        print("🎯 Samenwerkingsaccount gevonden.")
    except Exception as e:
        print(f"⚠️ Kon samenwerkingsaccount niet specifiek ophalen, gebruik volledige feed: {e}")

    # 7) Filter posts op samenwerkingsaccount (als bekend)
    working_posts = posts
    if target_did:
        filtered = [p for p in posts if getattr(p.post.author, "did", None) == target_did]
        if filtered:
            working_posts = filtered
            print(f"🎯 Aantal posts van samenwerkingsaccount in feed: {len(working_posts)}")
        else:
            print("ℹ️ Geen posts van samenwerkingsaccount in feed – gebruik volledige feed.")

    # sorteer op oud -> nieuw (op basis van createdAt)
    working_posts.sort(key=get_post_timestamp)

    me = bot_client.me

    # -----------------------------------
    # SELECTIE VAN POSTS VOOR DEZE RUN
    # -----------------------------------

    # nieuwste post in de (gefilterde) set
    newest_item = working_posts[-1]
    newest_uri = newest_item.post.uri

    # alle oudere posts uit dezelfde set
    older_items = working_posts[:-1]

    # filter: alleen repost-kandidaten die niet van jezelf zijn en niet in cooldown (voor OUDE posts)
    old_candidates = []
    for item in older_items:
        uri = item.post.uri
        author = item.post.author
        if author.did == me.did:
            continue
        if not can_repost(uri, repost_log):
            continue
        old_candidates.append(item)

    # nieuwste post is ALTIJD kandidaat zolang het geen eigen post is
    newest_candidate = None
    newest_author = newest_item.post.author
    if newest_author.did != me.did:
        newest_candidate = newest_item

    print(f"📊 Oude kandidaten (na cooldown): {len(old_candidates)}")
    print(f"📊 Nieuwste post {'kan' if newest_candidate else 'kan niet'} worden gebruikt (is geen eigen post).")

    # kies max 2 willekeurige oude posts
    chosen_old: List = []
    if old_candidates:
        chosen_old = random.sample(old_candidates, min(2, len(old_candidates)))
        # sorteer de gekozen oude posts zelf ook van oud -> minder oud
        chosen_old.sort(key=get_post_timestamp)

    # volgorde: twee oude posts eerst, daarna nieuwste (zodat nieuwste bovenaan komt op profiel)
    selected_items: List = []
    selected_items.extend(chosen_old)
    if newest_candidate is not None:
        selected_items.append(newest_candidate)

    if not selected_items:
        print("ℹ️ Geen geschikte posts om te repost-en deze run (cooldown/geen externe posts).")
        return

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

        is_newest = item is newest_candidate
        reason = "nieuwste post" if is_newest else "random oude"

        print("----------------------------------------")
        print(f"▶️ [{index}/{len(selected_items)}] Verwerken: {reason}")
        print(f"   Post URI: {uri}")

        # 1) Auteur volgen (zonder naam in log)
        ensure_follow(bot_client, author.did)

        # 2) Als dit de nieuwste is: oude repost (indien aanwezig) eerst verwijderen
        unrepost_if_needed(bot_client, post, is_newest=is_newest)

        # 3) Repost op hoofdaccount (ZONDER tekst)
        print("=== [2/6] Repost hoofdaccount ===")
        if not repost_post(bot_client, uri, cid, reason=reason):
            # als repost faalt, sla de rest van de stappen over voor deze post
            continue

        # 4) Like op hoofdaccount
        print("=== [3/6] Like hoofdaccount ===")
        like_post(bot_client, uri, cid)

        # 5) Likers volgen
        followed_now = follow_likers(bot_client, uri)
        total_followed += followed_now

        # 6) Stats-reply
        reply_with_stats(bot_client, uri, cid)

        # 7) Citaatpost op quote-account (@hotbleusky)
        quote_post(quote_client, uri, cid)

        # 8) Markeer in cooldown-log (maar NIET voor de nieuwste post)
        if not is_newest:
            mark_reposted(uri, repost_log)

    print("========================================")
    print(f"📈 Nieuwe accounts gevolgd via likes (alle posts): {total_followed}")
    print("✅ BF Promo Bot run afgerond.")
    print("========================================")


if __name__ == "__main__":
    main()
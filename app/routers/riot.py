import asyncio
import logging
from fastapi import APIRouter, Path
import aiohttp
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 600  # 10분
CHAMPION_DATA: dict = {}

GAME_MODE_KR = {
    "CLASSIC": "소환사의 협곡",
    "ARAM": "칼바람 나락",
    "URF": "우르프",
    "CHERRY": "아레나",
    "NEXUSBLITZ": "넥서스 블리츠",
    "ULTBOOK": "궁극기 주문서",
}


def _riot_headers() -> dict:
    return {
        "X-Riot-Token": settings.RIOT_API_KEY,
        "User-Agent": "JEE6-API/1.0",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Accept-Charset": "application/x-www-form-urlencoded; charset=UTF-8",
    }


async def _load_champion_data():
    global CHAMPION_DATA
    if CHAMPION_DATA:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://ddragon.leagueoflegends.com/api/versions.json") as resp:
                versions = await resp.json()
            version = versions[0]
            url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion.json"
            async with session.get(url) as resp:
                data = await resp.json()
            CHAMPION_DATA = {
                int(v["key"]): {"name": v["name"], "id": v["id"]}
                for v in data["data"].values()
            }
            logger.info(f"챔피언 데이터 로드 완료 (v{version}, {len(CHAMPION_DATA)}개)")
    except Exception as e:
        logger.error(f"챔피언 데이터 로드 실패: {e}")


async def _get_account(session: aiohttp.ClientSession, riot_id: str) -> dict:
    cached = await cache.get(f"riot:account:{riot_id}")
    if cached:
        return cached

    parts = riot_id.split("#")
    if len(parts) != 2:
        raise ValueError("닉네임#태그 형식이 필요합니다.")

    url = f"{settings.LOL_ASIA_URL}/riot/account/v1/accounts/by-riot-id/{parts[0]}/{parts[1]}"
    async with session.get(url, headers=_riot_headers()) as resp:
        if resp.status != 200:
            raise ValueError(f"계정을 찾을 수 없습니다: {riot_id}")
        data = await resp.json()

    await cache.set(f"riot:account:{riot_id}", data, ttl=CACHE_TTL)
    return data


# --- LoL ---

@router.get("/lol/tier/{riot_id}")
async def lol_tier(riot_id: str = Path(...)):
    cached = await cache.get(f"lol:tier:{riot_id}")
    if cached:
        return cached

    await _load_champion_data()

    async with aiohttp.ClientSession() as session:
        account = await _get_account(session, riot_id)
        puuid = account["puuid"]

        url = f"{settings.LOL_BASE_URL}/lol/summoner/v4/summoners/by-puuid/{puuid}"
        async with session.get(url, headers=_riot_headers()) as resp:
            summoner = await resp.json()

        url = f"{settings.LOL_BASE_URL}/lol/league/v4/entries/by-summoner/{summoner['id']}"
        async with session.get(url, headers=_riot_headers()) as resp:
            entries = await resp.json()

    solo = next((e for e in entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
    tier = f"{solo['tier']} {solo['rank']}" if solo else "Unranked"

    result = {"riot_id": riot_id, "solo_rank": solo, "tier": tier}
    await cache.set(f"lol:tier:{riot_id}", result, ttl=CACHE_TTL)
    return result


@router.get("/lol/history/{riot_id}")
async def lol_history(riot_id: str = Path(...)):
    cached = await cache.get(f"lol:history:{riot_id}")
    if cached:
        return cached

    await _load_champion_data()

    async with aiohttp.ClientSession() as session:
        account = await _get_account(session, riot_id)
        puuid = account["puuid"]

        url = f"{settings.LOL_ASIA_URL}/lol/match/v5/matches/by-puuid/{puuid}/ids?count=5"
        async with session.get(url, headers=_riot_headers()) as resp:
            match_ids = await resp.json()

        async def fetch_match(mid: str) -> dict | None:
            murl = f"{settings.LOL_ASIA_URL}/lol/match/v5/matches/{mid}"
            async with session.get(murl, headers=_riot_headers()) as r:
                if r.status != 200:
                    return None
                return await r.json()

        match_datas = await asyncio.gather(*[fetch_match(mid) for mid in match_ids])

    matches = []
    for md in match_datas:
        if not md:
            continue
        info = md.get("info", {})
        player = next((p for p in info.get("participants", []) if p["puuid"] == puuid), None)
        if not player:
            continue

        champ_id = player.get("championId", 0)
        champ = CHAMPION_DATA.get(champ_id, {}).get("name", str(champ_id))
        mode = GAME_MODE_KR.get(info.get("gameMode", ""), info.get("gameMode", ""))
        duration = info.get("gameDuration", 0)

        matches.append({
            "win": player.get("win", False),
            "champion": champ,
            "kills": player.get("kills", 0),
            "deaths": player.get("deaths", 0),
            "assists": player.get("assists", 0),
            "mode": mode,
            "duration": f"{duration // 60}:{duration % 60:02d}",
        })

    result = {"riot_id": riot_id, "matches": matches}
    await cache.set(f"lol:history:{riot_id}", result, ttl=CACHE_TTL)
    return result


@router.get("/lol/rotation")
async def lol_rotation():
    cached = await cache.get("lol:rotation")
    if cached:
        return cached

    await _load_champion_data()

    async with aiohttp.ClientSession() as session:
        url = f"{settings.LOL_BASE_URL}/lol/platform/v3/champion-rotations"
        async with session.get(url, headers=_riot_headers()) as resp:
            data = await resp.json()

    champ_ids = data.get("freeChampionIds", [])
    champions = [
        CHAMPION_DATA.get(cid, {"name": str(cid), "id": str(cid)})
        for cid in champ_ids
    ]

    result = {"champions": champions}
    await cache.set("lol:rotation", result, ttl=3600)
    return result


# --- Valorant ---

@router.get("/valo/tier/{riot_id}")
async def valo_tier(riot_id: str = Path(...)):
    cached = await cache.get(f"valo:tier:{riot_id}")
    if cached:
        return cached

    async with aiohttp.ClientSession() as session:
        account = await _get_account(session, riot_id)
        puuid = account["puuid"]

        url = f"{settings.VALO_AP_URL}/val/ranked/v1/by-puuid/{puuid}"
        async with session.get(url, headers=_riot_headers()) as resp:
            if resp.status != 200:
                return {"riot_id": riot_id, "tier": "Unranked"}
            data = await resp.json()

    tier = data.get("currenttierpatched", "Unranked") if data else "Unranked"
    result = {"riot_id": riot_id, "tier": tier}
    await cache.set(f"valo:tier:{riot_id}", result, ttl=CACHE_TTL)
    return result


@router.get("/valo/history/{riot_id}")
async def valo_history(riot_id: str = Path(...)):
    cached = await cache.get(f"valo:history:{riot_id}")
    if cached:
        return cached

    async with aiohttp.ClientSession() as session:
        account = await _get_account(session, riot_id)
        puuid = account["puuid"]

        url = f"{settings.VALO_AP_URL}/val/match/v1/matchlists/by-puuid/{puuid}"
        async with session.get(url, headers=_riot_headers()) as resp:
            data = await resp.json()

        match_ids = [m["matchId"] for m in data.get("history", [])[:5]]

        async def fetch_match(mid: str) -> dict | None:
            murl = f"{settings.VALO_AP_URL}/val/match/v1/matches/{mid}"
            async with session.get(murl, headers=_riot_headers()) as r:
                if r.status != 200:
                    return None
                return await r.json()

        match_datas = await asyncio.gather(*[fetch_match(mid) for mid in match_ids])

    matches = []
    for md in match_datas:
        if not md:
            continue
        info = md.get("matchInfo", {})
        players = md.get("players", [])
        player = next((p for p in players if p["puuid"] == puuid), None)
        if not player:
            continue

        stats = player.get("stats", {})
        team_id = player.get("teamId", "")
        teams = md.get("teams", [])
        team = next((t for t in teams if t.get("teamId") == team_id), {})

        matches.append({
            "win": team.get("won", False),
            "character": player.get("characterId", "?"),
            "kills": stats.get("kills", 0),
            "deaths": stats.get("deaths", 0),
            "assists": stats.get("assists", 0),
            "score": stats.get("score", 0),
            "map": info.get("mapId", "?"),
        })

    result = {"riot_id": riot_id, "matches": matches}
    await cache.set(f"valo:history:{riot_id}", result, ttl=CACHE_TTL)
    return result

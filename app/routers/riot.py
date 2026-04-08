import asyncio
import logging
import requests
from fastapi import APIRouter, Path
import aiohttp
from app.config import settings
from app import cache

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 600
CHAMPION_DATA: dict = {}

GAME_MODE_KR = {
    "CLASSIC": "소환사의 협곡",
    "ARAM": "칼바람 나락",
    "URF": "우르프",
    "ARURF": "무작위 우르프",
    "ONEFORALL": "단일 챔피언",
    "TUTORIAL": "튜토리얼",
    "PRACTICETOOL": "연습",
    "NEXUSBLITZ": "넥서스 돌격",
    "ULTBOOK": "궁극기 주문서",
}


def _riot_headers() -> dict:
    return {
        "X-Riot-Token": settings.RIOT_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Charset": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://developer.riotgames.com",
    }


def _load_champion_data_sync():
    global CHAMPION_DATA
    if CHAMPION_DATA:
        return
    try:
        version_response = requests.get("https://ddragon.leagueoflegends.com/api/versions.json")
        latest_version = version_response.json()[0]
        champions_url = f"http://ddragon.leagueoflegends.com/cdn/{latest_version}/data/ko_KR/champion.json"
        champions_response = requests.get(champions_url)
        CHAMPION_DATA = champions_response.json()
        logger.info(f"챔피언 데이터 로드 완료 (버전: {latest_version})")
    except Exception as e:
        logger.error(f"챔피언 데이터 로드 실패: {e}")
        CHAMPION_DATA = {"data": {}}


def _get_champion_name_kr(champion_id: str) -> str:
    return next(
        (
            champ_info["name"]
            for champ_name, champ_info in CHAMPION_DATA.get("data", {}).items()
            if champ_name == champion_id
        ),
        champion_id,
    )


async def _get_account(session: aiohttp.ClientSession, riot_id: str) -> dict:
    cached = await cache.get(f"riot:account:{riot_id}")
    if cached:
        return cached

    if "#" not in riot_id:
        raise ValueError("닉넴#태그 형식으로 입력하세요")

    game_name, tag_line = riot_id.split("#")
    url = f"{settings.LOL_ASIA_URL}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    async with session.get(url, headers=_riot_headers()) as resp:
        if resp.status != 200:
            raise ValueError(f"계정을 찾을 수 없습니다. (상태 코드: {resp.status})")
        data = await resp.json()

    await cache.set(f"riot:account:{riot_id}", data, ttl=CACHE_TTL)
    return data


@router.get("/lol/tier/{riot_id}")
async def lol_tier(riot_id: str = Path(...)):
    cached = await cache.get(f"lol:tier:{riot_id}")
    if cached:
        return cached

    _load_champion_data_sync()

    async with aiohttp.ClientSession() as session:
        account = await _get_account(session, riot_id)
        puuid = account["puuid"]

        url = f"{settings.LOL_BASE_URL}/lol/summoner/v4/summoners/by-puuid/{puuid}"
        async with session.get(url, headers=_riot_headers()) as resp:
            if resp.status != 200:
                return {"riot_id": riot_id, "solo_rank": None, "tier": "UNRANKED"}
            summoner = await resp.json()

        url = f"{settings.LOL_BASE_URL}/lol/league/v4/entries/by-summoner/{summoner['id']}"
        async with session.get(url, headers=_riot_headers()) as resp:
            if resp.status != 200:
                return {"riot_id": riot_id, "solo_rank": None, "tier": "UNRANKED"}
            entries = await resp.json()

    solo = next((e for e in entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
    tier = solo["tier"] if solo else "UNRANKED"

    result = {"riot_id": riot_id, "solo_rank": solo, "tier": tier}
    await cache.set(f"lol:tier:{riot_id}", result, ttl=CACHE_TTL)
    return result


@router.get("/lol/history/{riot_id}")
async def lol_history(riot_id: str = Path(...)):
    cached = await cache.get(f"lol:history:{riot_id}")
    if cached:
        return cached

    _load_champion_data_sync()

    async with aiohttp.ClientSession() as session:
        account = await _get_account(session, riot_id)
        puuid = account["puuid"]

        url = f"{settings.LOL_ASIA_URL}/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=5"
        async with session.get(url, headers=_riot_headers()) as resp:
            if resp.status != 200:
                raise ValueError("최근 게임 기록을 가져올 수 없습니다.")
            match_ids = await resp.json()

        if not match_ids:
            raise ValueError("최근 게임 기록이 없습니다.")

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

        champion_id = player.get("championName", "")
        champion_name = _get_champion_name_kr(champion_id)
        kills = player.get("kills", 0)
        deaths = player.get("deaths", 0)
        assists = player.get("assists", 0)
        kda = "Perfect" if deaths == 0 else round((kills + assists) / deaths, 2)
        win = player.get("win", False)
        duration = info.get("gameDuration", 0)
        minutes = duration // 60
        seconds = duration % 60
        game_mode = info.get("gameMode", "")
        kr_mode = GAME_MODE_KR.get(game_mode, game_mode)

        matches.append({
            "name": f"[{'승리' if win else '패배'}] - {champion_name}, {kr_mode}",
            "value": f"- **{kills}/{deaths}/{assists}** ({kda})\n- {minutes}분 {seconds}초",
        })

    result = {"riot_id": riot_id, "matches": matches}
    await cache.set(f"lol:history:{riot_id}", result, ttl=CACHE_TTL)
    return result


@router.get("/lol/rotation")
async def lol_rotation():
    cached = await cache.get("lol:rotation")
    if cached:
        return cached

    _load_champion_data_sync()

    async with aiohttp.ClientSession() as session:
        url = f"{settings.LOL_BASE_URL}/lol/platform/v3/champion-rotations"
        async with session.get(url, headers=_riot_headers()) as resp:
            if resp.status != 200:
                raise ValueError("로테이션 정보를 가져올 수 없습니다.")
            data = await resp.json()

    champion_info = []
    for champ_id in data.get("freeChampionIds", []):
        for champ_name, champ_data in CHAMPION_DATA.get("data", {}).items():
            if int(champ_data["key"]) == champ_id:
                champion_info.append({"kr_name": champ_data["name"], "en_name": champ_name})
                break

    result = {"champions": champion_info}
    await cache.set("lol:rotation", result, ttl=3600)
    return result


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
                return {
                    "riot_id": riot_id,
                    "account": account,
                    "rank_data": None,
                    "tier": "UNRANKED",
                }
            rank_data = await resp.json()

    if not rank_data or not rank_data.get("currenttier"):
        tier = "UNRANKED"
        rank_data = None
    else:
        tier = rank_data.get("currenttierpatched", "UNRANKED")

    result = {
        "riot_id": riot_id,
        "account": account,
        "rank_data": rank_data,
        "tier": tier,
    }
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
            if resp.status != 200:
                raise ValueError(f"매치 내역을 가져올 수 없습니다. (상태 코드: {resp.status})")
            matches_data = await resp.json()

        if "history" not in matches_data or not matches_data["history"]:
            raise ValueError("최근 게임 기록이 없습니다.")

        formatted_matches = []
        for match in matches_data["history"][:5]:
            match_id = match["matchId"]
            murl = f"{settings.VALO_AP_URL}/val/match/v1/matches/{match_id}"
            async with session.get(murl, headers=_riot_headers()) as r:
                if r.status != 200:
                    continue
                match_data = await r.json()

            player = next(
                (p for p in match_data["players"] if p["puuid"] == puuid), None
            )
            if not player:
                continue

            kills = player["stats"]["kills"]
            deaths = player["stats"]["deaths"]
            assists = player["stats"]["assists"]
            kda = "Perfect" if deaths == 0 else round((kills + assists) / deaths, 2)
            win_text = (
                "승리"
                if player["team"] == match_data["teams"][0]["teamId"]
                else "패배"
            )

            formatted_matches.append({
                "name": f"[{win_text}] - {player['character']}, {match_data['metadata']['map']}",
                "value": f"- **{kills}/{deaths}/{assists}** (KDA: {kda})\n- 점수: {player['stats']['score']}",
            })

    result = {"riot_id": riot_id, "account": account, "matches": formatted_matches}
    await cache.set(f"valo:history:{riot_id}", result, ttl=CACHE_TTL)
    return result

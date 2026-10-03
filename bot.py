import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import os
import re
import sqlite3
from urllib.parse import quote
from datetime import datetime, timedelta


# =========================================================
# 기본 설정
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DB_FILE = "rollhaja_games.db"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 .env 파일에 없습니다.")


# =========================================================
# 디스코드 봇 설정
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# 데이터베이스
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            thread_id INTEGER PRIMARY KEY,
            creator_id INTEGER NOT NULL,
            max_players INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            message_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            discord_id INTEGER NOT NULL,
            riot_name TEXT NOT NULL,
            riot_tag TEXT NOT NULL,
            tier TEXT NOT NULL,
            position TEXT NOT NULL,
            status TEXT NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(thread_id, discord_id)
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# 닉네임 형식
#
# 실제 형식:
# 00 억울합니다#제가던졌/P3/서폿
#
# 앞의 00 = 생년 → 무시
#
# 인식 결과:
# 롤 닉네임 = 억울합니다
# 태그 = 제가던졌
# 티어 = P3
# 주라인 = 서폿
# =========================================================

NICKNAME_PATTERN = re.compile(
    r"^\d{2}\s+"
    r"(.+?)#(.+?)"
    r"\s*/\s*"
    r"(GM[1-9]\d*|C[1-9]\d*|M[1-9]\d*|"
    r"I[1-4]|B[1-4]|S[1-4]|G[1-4]|P[1-4]|E[1-4]|D[1-4])"
    r"\s*/\s*"
    r"(탑|정글|미드|원딜|서폿|서포터)"
    r"$"
)


def parse_nickname(display_name):

    match = NICKNAME_PATTERN.match(
        display_name.strip()
    )

    if not match:
        return None

    riot_name = match.group(1).strip()
    riot_tag = match.group(2).strip()
    tier = match.group(3).strip()
    position = match.group(4).strip()

    if position == "서포터":
        position = "서폿"

    return {
        "riot_name": riot_name,
        "riot_tag": riot_tag,
        "tier": tier,
        "position": position
    }


# =========================================================
# FOW 링크
# =========================================================

def make_fow_url(riot_name, riot_tag):

    riot_id = f"{riot_name}-{riot_tag}"

    return (
        "https://m3.fow.kr/?name="
        + quote(riot_id, safe="")
    )


# =========================================================
# 게임 정보
# =========================================================

def get_game(thread_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM games WHERE thread_id = ?",
        (thread_id,)
    )

    game = cur.fetchone()

    conn.close()

    return game


def get_players(thread_id, status=None):

    conn = get_db()
    cur = conn.cursor()

    if status:

        cur.execute(
            """
            SELECT *
            FROM players
            WHERE thread_id = ?
            AND status = ?
            ORDER BY joined_at ASC, id ASC
            """,
            (
                thread_id,
                status
            )
        )

    else:

        cur.execute(
            """
            SELECT *
            FROM players
            WHERE thread_id = ?
            ORDER BY joined_at ASC, id ASC
            """,
            (thread_id,)
        )

    players = cur.fetchall()

    conn.close()

    return players


# =========================================================
# 시작 시간 계산
# =========================================================

def get_start_datetime(start_time):

    hour, minute = map(
        int,
        start_time.split(":")
    )

    now = datetime.now()

    start = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0
    )

    # 이미 오늘 시간이 지나갔다면 다음 날로 계산
    if start <= now:
        start += timedelta(days=1)

    return start


def is_game_locked(game):

    start_datetime = get_start_datetime(
        game["start_time"]
    )

    now = datetime.now()

    remaining = start_datetime - now

    # 시작 30분 전부터 잠금
    return remaining <= timedelta(minutes=30)


def get_lock_message():

    return (
        "🔒 **참여 및 취소가 잠겼습니다.**\n"
        "내전 시작 30분 전부터 신청과 취소가 제한됩니다."
    )


# =========================================================
# 내전 Embed 생성
# =========================================================

def create_game_embed(thread_id):

    game = get_game(thread_id)

    if not game:
        return None

    max_players = game["max_players"]
    start_time = game["start_time"]

    participants = get_players(
        thread_id,
        "participant"
    )

    waiters = get_players(
        thread_id,
        "waitlist"
    )

    lines = []

    # 시작 시간
    lines.append("🕐 **시작 시간**")
    lines.append(start_time)
    lines.append("")

    # 모집 인원
    lines.append("👥 **모집 인원**")
    lines.append(f"{max_players}명")
    lines.append("")

    # 참여자
    lines.append(
        f"☑️ 👤 **참여자 ({len(participants)}/{max_players})**"
    )

    for index in range(max_players):

        if index < len(participants):

            player = participants[index]

            fow_url = make_fow_url(
                player["riot_name"],
                player["riot_tag"]
            )

            nickname = (
                f"{player['riot_name']}#{player['riot_tag']}"
            )

            lines.append(
                f"{index + 1}. "
                f"[{nickname}]({fow_url}) / "
                f"{player['tier']} / "
                f"{player['position']}"
            )

        else:

            lines.append(
                f"{index + 1}. -"
            )

    lines.append("")

    # 대기자
    lines.append("⏳ 👤 **대기자**")

    if waiters:

        for index, player in enumerate(
            waiters,
            start=1
        ):

            fow_url = make_fow_url(
                player["riot_name"],
                player["riot_tag"]
            )

            nickname = (
                f"{player['riot_name']}#{player['riot_tag']}"
            )

            lines.append(
                f"{index}. "
                f"[{nickname}]({fow_url}) / "
                f"{player['tier']} / "
                f"{player['position']}"
            )

    else:

        lines.append("없음")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("참여하려면 `ㅅ` 또는 `손`")
    lines.append("취소하려면 `ㅊ` 또는 `취소`")
    lines.append("")

    # 30분 전 잠금 표시
    if is_game_locked(game):
        lines.append("🔒 **현재 신청 및 취소가 잠겨 있습니다.**")
        lines.append("")

    lines.append("📝 **닉네임 형식**")
    lines.append(
        "생년 롤 닉네임#태그/티어/주라인"
    )
    lines.append("")
    lines.append("예시")
    lines.append(
        "00 억울합니다#제가던졌/P3/서폿"
    )

    embed = discord.Embed(
        description="\n".join(lines),
        color=discord.Color.dark_grey()
    )

    return embed


# =========================================================
# 모집 메시지 업데이트
# =========================================================

async def update_game_message(thread):

    game = get_game(thread.id)

    if not game:
        return

    message_id = game["message_id"]

    if not message_id:
        return

    try:

        message = await thread.fetch_message(
            message_id
        )

        embed = create_game_embed(
            thread.id
        )

        if embed:

            await message.edit(
                embed=embed
            )

    except discord.NotFound:

        pass

    except discord.Forbidden:

        print(
            f"[오류] 게시물 메시지를 수정할 권한이 없습니다: "
            f"{thread.id}"
        )

    except Exception as e:

        print(
            f"[오류] 모집 메시지 업데이트 실패: {e}"
        )


# =========================================================
# /내전생성
# =========================================================

@bot.tree.command(
    name="내전생성",
    description="현재 포럼 게시물을 내전 모집으로 활성화합니다."
)
@app_commands.describe(
    인원="참여할 최대 인원",
    시작시간="시작 시간 예: 22:00"
)
async def 내전생성(
    interaction: discord.Interaction,
    인원: app_commands.Range[int, 2, 50],
    시작시간: str
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "서버에서만 사용할 수 있습니다.",
            ephemeral=True
        )

        return

    if not interaction.user.guild_permissions.manage_guild:

        await interaction.response.send_message(
            "이 명령어는 서버 관리 권한이 있는 사람만 사용할 수 있습니다.",
            ephemeral=True
        )

        return

    if not isinstance(
        interaction.channel,
        discord.Thread
    ):

        await interaction.response.send_message(
            "이 명령어는 포럼 게시물 안에서 사용해주세요.",
            ephemeral=True
        )

        return

    if not isinstance(
        interaction.channel.parent,
        discord.ForumChannel
    ):

        await interaction.response.send_message(
            "포럼 게시물 안에서 사용해주세요.",
            ephemeral=True
        )

        return

    thread = interaction.channel

    if get_game(thread.id):

        await interaction.response.send_message(
            "이 게시물은 이미 내전 모집으로 사용 중입니다.",
            ephemeral=True
        )

        return

    if not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d",
        시작시간.strip()
    ):

        await interaction.response.send_message(
            "시작 시간은 `HH:MM` 형식으로 입력해주세요.\n"
            "예: `22:00`",
            ephemeral=True
        )

        return

    start_time = 시작시간.strip()

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO games (
            thread_id,
            creator_id,
            max_players,
            start_time,
            message_id
        )
        VALUES (?, ?, ?, ?, NULL)
        """,
        (
            thread.id,
            interaction.user.id,
            인원,
            start_time
        )
    )

    conn.commit()
    conn.close()

    embed = create_game_embed(
        thread.id
    )

    try:

        message = await thread.send(
            embed=embed
        )

    except Exception as e:

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM games WHERE thread_id = ?",
            (thread.id,)
        )

        conn.commit()
        conn.close()

        await interaction.response.send_message(
            f"내전 생성 중 오류가 발생했습니다.\n"
            f"`{e}`",
            ephemeral=True
        )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE games
        SET message_id = ?
        WHERE thread_id = ?
        """,
        (
            message.id,
            thread.id
        )
    )

    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"✅ 내전 모집이 생성되었습니다!\n"
        f"모집 인원: **{인원}명**\n"
        f"시작 시간: **{start_time}**",
        ephemeral=True
    )


# =========================================================
# ㅅ / 손 참가 처리
# =========================================================

async def join_game(message, game):

    thread = message.channel

    # =====================================================
    # 30분 전 잠금 확인
    # =====================================================

    if is_game_locked(game):

        try:

            warning = await message.reply(
                get_lock_message(),
                mention_author=False
            )

            await warning.delete(
                delay=5
            )

        except Exception:
            pass

        return

    # =====================================================
    # 닉네임 확인
    # =====================================================

    nickname_data = parse_nickname(
        message.author.display_name
    )

    if not nickname_data:

        try:

            warning = await message.reply(
                "❌ 닉네임 형식이 올바르지 않습니다.\n"
                "`생년 롤 닉네임#태그/티어/주라인`\n\n"
                "예시: `00 억울합니다#제가던졌/P3/서폿`",
                mention_author=False
            )

            await warning.delete(
                delay=10
            )

        except Exception:
            pass

        return

    # =====================================================
    # 중복 확인
    # =====================================================

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM players
        WHERE thread_id = ?
        AND discord_id = ?
        """,
        (
            thread.id,
            message.author.id
        )
    )

    existing = cur.fetchone()

    conn.close()

    if existing:

        try:

            warning = await message.reply(
                "⚠️ 이미 이 내전에 신청되어 있습니다.",
                mention_author=False
            )

            await warning.delete(
                delay=5
            )

        except Exception:
            pass

        return

    # =====================================================
    # 참가자 수 확인
    # =====================================================

    participants = get_players(
        thread.id,
        "participant"
    )

    if len(participants) < game["max_players"]:

        status = "participant"

        result_text = (
            "✅ 내전 참여자로 등록되었습니다!"
        )

    else:

        status = "waitlist"

        result_text = (
            "⏳ 모집 인원이 가득 차 "
            "대기자로 등록되었습니다!"
        )

    # =====================================================
    # DB 저장
    # =====================================================

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO players (
            thread_id,
            discord_id,
            riot_name,
            riot_tag,
            tier,
            position,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread.id,
            message.author.id,
            nickname_data["riot_name"],
            nickname_data["riot_tag"],
            nickname_data["tier"],
            nickname_data["position"],
            status
        )
    )

    conn.commit()
    conn.close()

    # =====================================================
    # Embed 업데이트
    # =====================================================

    await update_game_message(
        thread
    )

    # =====================================================
    # 결과 메시지
    # =====================================================

    try:

        response = await message.reply(
            result_text,
            mention_author=False
        )

        await response.delete(
            delay=5
        )

    except Exception:
        pass


# =========================================================
# ㅊ / 취소 처리
# =========================================================

async def cancel_game(message, game):

    thread = message.channel

    # =====================================================
    # 30분 전 잠금 확인
    # =====================================================

    if is_game_locked(game):

        try:

            warning = await message.reply(
                get_lock_message(),
                mention_author=False
            )

            await warning.delete(
                delay=5
            )

        except Exception:
            pass

        return

    # =====================================================
    # 본인 신청 정보 확인
    # =====================================================

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM players
        WHERE thread_id = ?
        AND discord_id = ?
        """,
        (
            thread.id,
            message.author.id
        )
    )

    player = cur.fetchone()

    if not player:

        conn.close()

        try:

            warning = await message.reply(
                "❌ 현재 이 내전에 신청되어 있지 않습니다.",
                mention_author=False
            )

            await warning.delete(
                delay=5
            )

        except Exception:
            pass

        return

    # =====================================================
    # 참가자였는지 확인
    # =====================================================

    was_participant = (
        player["status"] == "participant"
    )

    # =====================================================
    # 본인 신청 삭제
    # =====================================================

    cur.execute(
        """
        DELETE FROM players
        WHERE thread_id = ?
        AND discord_id = ?
        """,
        (
            thread.id,
            message.author.id
        )
    )

    # =====================================================
    # 참가자 취소라면 대기자 1번 자동 승급
    # =====================================================

    promoted_player = None

    if was_participant:

        cur.execute(
            """
            SELECT *
            FROM players
            WHERE thread_id = ?
            AND status = 'waitlist'
            ORDER BY joined_at ASC, id ASC
            LIMIT 1
            """,
            (thread.id,)
        )

        promoted_player = cur.fetchone()

        if promoted_player:

            cur.execute(
                """
                UPDATE players
                SET status = 'participant'
                WHERE id = ?
                """,
                (
                    promoted_player["id"],
                )
            )

    conn.commit()
    conn.close()

    # =====================================================
    # Embed 업데이트
    # =====================================================

    await update_game_message(
        thread
    )

    # =====================================================
    # 결과 메시지
    # =====================================================

    if was_participant:

        if promoted_player:

            result_text = (
                "❎ 신청이 취소되었습니다.\n"
                "⬆️ 대기자 1번이 참여자로 자동 승급되었습니다."
            )

        else:

            result_text = (
                "❎ 내전 신청이 취소되었습니다."
            )

    else:

        result_text = (
            "❎ 대기 신청이 취소되었습니다."
        )

    try:

        response = await message.reply(
            result_text,
            mention_author=False
        )

        await response.delete(
            delay=5
        )

    except Exception:
        pass


# =========================================================
# 메시지 감지
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    await bot.process_commands(
        message
    )

    if not isinstance(
        message.channel,
        discord.Thread
    ):
        return

    thread = message.channel

    game = get_game(
        thread.id
    )

    if not game:
        return

    content = message.content.strip()

    # =====================================================
    # 참가
    # =====================================================

    if content in (
        "ㅅ",
        "손"
    ):

        await join_game(
            message,
            game
        )

        return

    # =====================================================
    # 취소
    # =====================================================

    if content in (
        "ㅊ",
        "취소"
    ):

        await cancel_game(
            message,
            game
        )

        return


# =========================================================
# 봇 시작
# =========================================================

@bot.event
async def on_ready():

    init_db()

    print(
        f"로그인 완료: {bot.user}"
    )

    print(
        f"봇 ID: {bot.user.id}"
    )

    try:

        total = 0

        for guild in bot.guilds:

            guild_object = discord.Object(
                id=guild.id
            )

            bot.tree.copy_global_to(
                guild=guild_object
            )

            synced = await bot.tree.sync(
                guild=guild_object
            )

            total += len(synced)

            print(
                f"슬래시 명령어 동기화 완료: "
                f"{guild.name} / {len(synced)}개"
            )

        print(
            f"전체 슬래시 명령어 동기화 완료: {total}개"
        )

    except Exception as e:

        print(
            f"슬래시 명령어 동기화 오류: {e}"
        )


# =========================================================
# 실행
# =========================================================

bot.run(TOKEN)
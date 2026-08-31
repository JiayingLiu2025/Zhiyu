from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from email.utils import parsedate_to_datetime
import html
import json
import math
import re
import sqlite3
import threading
import time
import webbrowser


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "app.db"
TEMPLATE_PATH = BASE_DIR / "templates" / "index.html"
STATIC_DIR = BASE_DIR / "static"
CONTENT_VERSION = "2026-08-31-interests-v6"
CONTENT_REFRESH_INTERVAL = 30 * 60
CONTENT_REFRESH_TIMEOUT = 8
ONLINE_REFRESH_LOCK = threading.Lock()

DEFAULT_LOCKED = []
DEFAULT_DISLIKED = []

ONLINE_QUERIES = [
    ("乡村音乐", "乡村音乐 country music Billboard"),
    ("羽毛球男单", "羽毛球 男单 BWF"),
    ("皇马", "皇马 Bellingham Mbappe"),
    ("独立电影", "独立电影 新片 上映"),
    ("掌机", "掌机 游戏 新作"),
    ("夜跑", "城市夜跑 活动"),
    ("K-pop", "K-pop comeback Billboard"),
    ("羽毛球女单", "羽毛球 女单 BWF"),
    ("英超", "英超 最新"),
    ("纪录片", "纪录片 新作 上映"),
    ("Steam", "Steam 新游戏 发布"),
    ("短途旅行", "周末短途旅行 目的地"),
    ("现场演出", "现场演出 演唱会 最新"),
    ("混双", "羽毛球 混双 战术"),
    ("西甲", "西甲 焦点战 最新"),
    ("悬疑电影", "悬疑电影 新片"),
    ("独立游戏", "独立游戏 新作"),
    ("夜市", "夜市 小吃 最新"),
    ("音乐节", "音乐节 阵容 最新"),
    ("青少年羽毛球", "青少年 羽毛球 比赛"),
    ("欧冠", "欧冠 抽签 最新"),
    ("动画电影", "动画电影 预告 新片"),
    ("咖啡店", "咖啡店 新店 季节限定"),
    ("黑胶唱片", "黑胶唱片 再版 新发行"),
]

KEYWORD_BATCHES = [
    {
        "name": "今天想看什么",
        "source": "音乐 · 比赛 · 电影 · 游戏",
        "keywords": ["乡村音乐", "羽毛球男单", "皇马", "独立电影", "掌机", "夜跑"],
    },
    {
        "name": "周末灵感",
        "source": "榜单 · 赛场 · 新作 · 出发",
        "keywords": ["K-pop", "羽毛球女单", "英超", "纪录片", "Steam", "短途旅行"],
    },
    {
        "name": "跟着现场走",
        "source": "现场演出 · 对局 · 院线 · 城市",
        "keywords": ["现场演出", "混双", "西甲", "悬疑电影", "独立游戏", "夜市"],
    },
    {
        "name": "再挖一层",
        "source": "小切口 · 邻近发现",
        "keywords": ["音乐节", "青少年羽毛球", "欧冠", "动画电影", "咖啡店", "黑胶唱片"],
    },
]

BOUNDARY_BATCHES = [
    {
        "name": "先从兴趣说起",
        "keywords": ["乡村音乐", "羽毛球男单", "皇马", "独立电影", "掌机", "夜跑", "咖啡店", "夜市"],
    },
    {
        "name": "再选一个小方向",
        "keywords": ["K-pop", "羽毛球女单", "英超", "纪录片", "Steam", "短途旅行", "现场演出", "悬疑电影"],
    },
    {
        "name": "让推荐更像你",
        "keywords": ["混双", "西甲", "独立游戏", "音乐节", "动画电影", "青少年羽毛球", "黑胶唱片", "街头甜品"],
    },
]

DEFAULT_CATALOG = [
    {
        "title": "乡村音乐：Ella Langley 的冠军单曲继续领跑",
        "category": "乡村音乐",
        "summary": "Ella Langley 的《Choosin' Texas》在 Billboard Hot 100 连续 19 周登顶，乡村音乐正在继续向主流榜单中心靠近。",
        "reason": "这是一条具体的榜单新闻，后续会优先替换成更新的乡村音乐报道。",
        "vibe": "高频更新",
        "base": 94,
        "fixed": 0,
    },
    {
        "title": "羽毛球男单：世锦赛冠军争夺进入关键回合",
        "category": "羽毛球男单",
        "summary": "2026 年世界羽毛球锦标赛在新德里举行，男单赛场的对阵和最后几分，成为赛事报道里的高频看点。",
        "reason": "体育内容时效性强，后台会按固定间隔重新抓取公开报道。",
        "vibe": "赛程雷达",
        "base": 92,
        "fixed": 0,
    },
    {
        "title": "皇马：4 比 0 击败马拉加，贝林厄姆破门",
        "category": "皇马",
        "summary": "皇马 4 比 0 击败马拉加，贝林厄姆完成一条龙破门并制造乌龙，姆巴佩也收获进球。",
        "reason": "皇马是一条明确的球队兴趣，适合从赛果和球员表现继续往下追。",
        "vibe": "赛后速报",
        "base": 89,
        "fixed": 0,
    },
    {
        "title": "独立电影：小成本作品正在获得更多讨论",
        "category": "独立电影",
        "summary": "独立电影的新消息常常从影展和口碑发酵开始，一部小成本作品也可能因为一个导演或一个演员被更多人看见。",
        "reason": "独立电影从影展、导演和口碑切入，能把泛泛看片变成具体发现。",
        "vibe": "片单发现",
        "base": 87,
        "fixed": 0,
    },
    {
        "title": "掌机：新作把通勤时间变成一段冒险",
        "category": "掌机",
        "summary": "掌机新作的新闻通常很短：一个发布日期、一段试玩视频，或者一个让玩家重新拿起设备的玩法。",
        "reason": "掌机从设备和玩法切入，适合继续发现具体作品，而不是停留在泛游戏资讯。",
        "vibe": "轻量游玩",
        "base": 86,
        "fixed": 0,
    },
    {
        "title": "夜跑：城市夜色里出现新的运动路线",
        "category": "夜跑",
        "summary": "夜跑路线的有趣之处不只在距离，也在沿途的灯光、补给点和一起出发的人。短路线也可以成为新的城市入口。",
        "reason": "把可执行的小兴趣放进地图，探索才会真的走出去。",
        "vibe": "城市运动",
        "base": 84,
        "fixed": 0,
    },
    {
        "title": "阅读：今天读一篇短一点的",
        "category": "阅读",
        "summary": "从文化、人物和生活观察里找一篇不需要连续投入太久的内容。",
        "reason": "探索不只有热点，也可以有一条安静的支线。",
        "vibe": "安静支线",
        "base": 80,
        "fixed": 0,
    },
    {
        "title": "穿搭：把本季流行穿得像自己",
        "category": "穿搭",
        "summary": "看看颜色、鞋包和轻户外单品最近怎么搭，挑一个能落地的灵感。",
        "reason": "从流行乐出发，风格和生活方式是很近的一步。",
        "vibe": "风格试穿",
        "base": 78,
        "fixed": 0,
    },
    {
        "title": "宠物：今天和小动物有关的好消息",
        "category": "宠物",
        "summary": "收集领养、照护和有趣观察，让地图保留一点柔软的转弯。",
        "reason": "不是每条内容都要高强度，轻松的兴趣也值得被看见。",
        "vibe": "柔软转弯",
        "base": 76,
        "fixed": 0,
    },
]

DEFAULT_CATALOG.extend(
    [
        {
            "title": "K-pop：新专辑首周数据成为讨论中心",
            "category": "K-pop",
            "summary": "新专辑发布后，首周销量、舞台表现和粉丝二创往往同时升温。先听主打歌，再看看哪首歌被现场带起来。",
            "reason": "这是一个具体的音乐事件入口，后续会用最新榜单或新歌报道替换。",
            "vibe": "榜单现场",
            "base": 86,
            "fixed": 0,
        },
        {
            "title": "羽毛球女单：一拍多拍拉锯决定比赛节奏",
            "category": "羽毛球女单",
            "summary": "女单比赛的看点常常在落点变化和连续防守，最后几分的耐心比单次重杀更能改变比分。",
            "reason": "从具体打法切入，比泛泛看赛事更容易找到喜欢的选手。",
            "vibe": "打法观察",
            "base": 85,
            "fixed": 0,
        },
        {
            "title": "英超：新赛季第一轮的意外结果",
            "category": "英超",
            "summary": "英超新闻总有一场比赛先抢走注意力：强队失分、新人进球，或者补时阶段突然改变结果。",
            "reason": "体育热点变化快，在线排序会优先处理更新更近的报道。",
            "vibe": "赛果速报",
            "base": 84,
            "fixed": 0,
        },
        {
            "title": "纪录片：一个真实人物撑起整部新作",
            "category": "纪录片",
            "summary": "新纪录片常从一个人物或一段旧档案出发，把普通生活拍成值得追看的故事。",
            "reason": "适合从新闻标题继续走到导演、人物和真实背景。",
            "vibe": "真实故事",
            "base": 82,
            "fixed": 0,
        },
        {
            "title": "Steam：玩家把一款小体量新作顶上热榜",
            "category": "Steam",
            "summary": "一款游戏突然被讨论，可能只是因为玩法够简单、评价够真诚，或者朋友们都在同一晚打开了它。",
            "reason": "从玩家口碑切入，比只看大作发布更容易遇到意外。",
            "vibe": "玩家口碑",
            "base": 81,
            "fixed": 0,
        },
        {
            "title": "短途旅行：一座小城的周末路线",
            "category": "短途旅行",
            "summary": "不用排长假，一座两小时可达的小城也能装下老街、河岸和一顿当地晚饭。",
            "reason": "从短路线开始，探索成本更低，也更容易真的出发。",
            "vibe": "周末出发",
            "base": 79,
            "fixed": 0,
        },
        {
            "title": "现场演出：一首歌把观众从座位上带起来",
            "category": "现场演出",
            "summary": "现场新闻里最有画面的部分，常常不是歌单，而是某一首歌响起时全场一起合唱的瞬间。",
            "reason": "从一场演出继续找艺人、场地和下一场现场。",
            "vibe": "在场感",
            "base": 83,
            "fixed": 0,
        },
        {
            "title": "混双：前场抢网把比赛拉进快节奏",
            "category": "混双",
            "summary": "混双的精彩经常发生在网前，抢到第一拍就能把对手推入被动，连续几个回合很快就改变局面。",
            "reason": "具体战术会让赛事内容更有可看性。",
            "vibe": "战术切口",
            "base": 80,
            "fixed": 0,
        },
        {
            "title": "西甲：一场焦点战改变积分榜叙事",
            "category": "西甲",
            "summary": "西甲焦点战的价值不只在比分，还在谁掌握控球、谁在关键时刻把机会变成进球。",
            "reason": "从比赛细节进入，比只记住赛果更容易形成自己的判断。",
            "vibe": "赛场细节",
            "base": 82,
            "fixed": 0,
        },
        {
            "title": "悬疑电影：观众开始争论真正的凶手",
            "category": "悬疑电影",
            "summary": "悬疑片最有趣的时刻，往往是看完之后大家开始复盘同一个细节，发现它早就把答案放在镜头里。",
            "reason": "从一个反转或争议点继续找到同类型作品。",
            "vibe": "反转讨论",
            "base": 83,
            "fixed": 0,
        },
        {
            "title": "独立游戏：一个机制让玩家重新开始",
            "category": "独立游戏",
            "summary": "独立游戏不一定靠大场面留住玩家，有时只是一个很小但很聪明的机制，就足以让人想再试一次。",
            "reason": "适合从玩家评价继续探索创作者和玩法。",
            "vibe": "机制发现",
            "base": 80,
            "fixed": 0,
        },
        {
            "title": "夜市：一口小吃成为城市记忆点",
            "category": "夜市",
            "summary": "夜市新闻总会从一种小吃开始：排队的人、摊主的手艺和只在晚上出现的香味，都值得顺路看看。",
            "reason": "从一条具体食物消息出发，探索一座城市的夜生活。",
            "vibe": "街头味道",
            "base": 78,
            "fixed": 0,
        },
        {
            "title": "音乐节：阵容公布后，谁最先冲上热搜",
            "category": "音乐节",
            "summary": "音乐节阵容一公布，观众就开始排自己的必看名单，最意外的名字往往会带来新的发现。",
            "reason": "从艺人阵容切入，内容会继续跟进演出消息和现场反馈。",
            "vibe": "阵容雷达",
            "base": 79,
            "fixed": 0,
        },
        {
            "title": "青少年羽毛球：基本功正在决定比赛上限",
            "category": "青少年羽毛球",
            "summary": "青少年比赛里，步伐、发球和回球稳定性会比一记漂亮的扣杀更早拉开差距。",
            "reason": "从训练细节进入，能看到赛事之外的成长故事。",
            "vibe": "成长观察",
            "base": 77,
            "fixed": 0,
        },
        {
            "title": "欧冠：抽签结果让小组赛提前升温",
            "category": "欧冠",
            "summary": "抽签一公布，强强对话和旧将重逢就会成为讨论中心，赛季还没开始，故事已经先写了一半。",
            "reason": "从抽签这一具体事件开始，后续可以顺着球队和球员继续探索。",
            "vibe": "赛季预热",
            "base": 84,
            "fixed": 0,
        },
        {
            "title": "动画电影：一段预告片先把世界观打开",
            "category": "动画电影",
            "summary": "动画电影的新预告常常只露出几个角色和一个场景，却足够让观众开始猜故事会怎么展开。",
            "reason": "从画面和角色切入，适合继续发现导演、配音和原作。",
            "vibe": "预告观察",
            "base": 81,
            "fixed": 0,
        },
        {
            "title": "咖啡店：一杯季节限定拉来新的客人",
            "category": "咖啡店",
            "summary": "季节限定饮品、老店换菜单和小店的新开张，都是城市里很轻但很具体的好消息。",
            "reason": "从一杯咖啡出发，探索附近的店、街区和生活方式。",
            "vibe": "城市漫游",
            "base": 76,
            "fixed": 0,
        },
        {
            "title": "黑胶唱片：旧专辑重新回到播放列表",
            "category": "黑胶唱片",
            "summary": "一张旧专辑重新发行，可能因为封面、音色或一首被短视频带火的老歌，再次回到年轻人的播放列表。",
            "reason": "从一张具体唱片进入，可以继续追到乐队、年代和收藏故事。",
            "vibe": "旧声新听",
            "base": 75,
            "fixed": 0,
        },
    ]
)


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def set_pref(conn, key, value):
    conn.execute(
        "INSERT INTO preferences(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value),
    )


def get_pref(conn, key, default):
    row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    raw = row["value"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def clean_feed_text(value):
    value = html.unescape(value or "")
    return re.sub(r"<[^>]+>", " ", value).strip()


def compact_summary(value, limit=180):
    text = re.sub(r"\s+", " ", clean_feed_text(value))
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    short = ""
    for sentence in sentences:
        if not sentence:
            continue
        candidate = f"{short}{sentence}"
        if len(candidate) > limit:
            break
        short = candidate
        if len(short) >= 70:
            break
    return short or f"{text[:limit - 1]}…"


def published_timestamp(value):
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0


def fetch_online_items(category, query):
    params = urlencode(
        {
            "q": query,
            "hl": "zh-CN",
            "gl": "CN",
            "ceid": "CN:zh-Hans",
        }
    )
    request = Request(
        f"https://news.google.com/rss/search?{params}",
        headers={"User-Agent": "ActiveMapDB/1.0"},
    )
    with urlopen(request, timeout=CONTENT_REFRESH_TIMEOUT) as response:
        root = ElementTree.fromstring(response.read())

    items = []
    for node in root.findall("./channel/item")[:3]:
        title = clean_feed_text(node.findtext("title"))
        link = (node.findtext("link") or "").strip()
        description = clean_feed_text(node.findtext("description"))
        published_at = (node.findtext("pubDate") or "").strip()
        published_ts = published_timestamp(published_at)
        if title and link:
            items.append(
                {
                    "title": title,
                    "category": category,
                    "summary": compact_summary(description) or f"来自公开资讯的{category}最新动态。",
                    "reason": f"这是从公开资讯源抓到的{category}内容，会随下一轮更新。",
                    "vibe": "在线更新",
                    "base": 91 if category in DEFAULT_LOCKED else 82,
                    "fixed": 1 if category in DEFAULT_LOCKED else 0,
                    "origin": "online",
                    "source_url": link,
                    "published_at": published_at,
                    "published_ts": published_ts,
                }
            )
    return items


def refresh_online_content(force=False):
    if not ONLINE_REFRESH_LOCK.acquire(blocking=False):
        return False
    try:
        with connect() as conn:
            last_update = float(get_pref(conn, "online_updated_at", 0) or 0)
            if not force and time.time() - last_update < CONTENT_REFRESH_INTERVAL:
                return False

        fresh_items = []
        seen_links = set()
        for category, query in ONLINE_QUERIES:
            try:
                for item in fetch_online_items(category, query)[:2]:
                    if item["source_url"] in seen_links:
                        continue
                    seen_links.add(item["source_url"])
                    fresh_items.append(item)
            except Exception:
                continue

        if not fresh_items:
            return False

        with connect() as conn:
            conn.execute("DELETE FROM catalog WHERE origin = 'online'")
            conn.executemany(
                """
                INSERT INTO catalog(
                    title, category, summary, reason, vibe, base, fixed,
                    origin, source_url, published_at, published_ts
                )
                VALUES(
                    :title, :category, :summary, :reason, :vibe, :base, :fixed,
                    :origin, :source_url, :published_at, :published_ts
                )
                """,
                fresh_items,
            )
            set_pref(conn, "online_updated_at", time.time())
        return True
    finally:
        ONLINE_REFRESH_LOCK.release()


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                reason TEXT NOT NULL,
                vibe TEXT NOT NULL,
                base INTEGER NOT NULL DEFAULT 80,
                fixed INTEGER NOT NULL DEFAULT 0,
                origin TEXT NOT NULL DEFAULT 'local',
                source_url TEXT,
                published_at TEXT,
                published_ts REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT,
                category TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(catalog)").fetchall()}
        if "origin" not in columns:
            conn.execute("ALTER TABLE catalog ADD COLUMN origin TEXT NOT NULL DEFAULT 'local'")
        if "source_url" not in columns:
            conn.execute("ALTER TABLE catalog ADD COLUMN source_url TEXT")
        if "published_at" not in columns:
            conn.execute("ALTER TABLE catalog ADD COLUMN published_at TEXT")
        if "published_ts" not in columns:
            conn.execute("ALTER TABLE catalog ADD COLUMN published_ts REAL NOT NULL DEFAULT 0")

        if get_pref(conn, "content_version", "") != CONTENT_VERSION:
            conn.execute("DELETE FROM catalog")
            conn.executemany(
                """
                INSERT INTO catalog(
                    title, category, summary, reason, vibe, base, fixed, origin
                )
                VALUES(:title, :category, :summary, :reason, :vibe, :base, :fixed, 'local')
                """,
                DEFAULT_CATALOG,
            )
            set_pref(conn, "content_version", CONTENT_VERSION)
            set_pref(conn, "disliked", DEFAULT_DISLIKED)
            set_pref(conn, "seen", [])
            set_pref(conn, "trace_keywords", [])
            set_pref(conn, "online_updated_at", 0)

        count = conn.execute("SELECT COUNT(*) AS c FROM catalog").fetchone()["c"]
        if count == 0:
            conn.executemany(
                """
                INSERT INTO catalog(
                    title, category, summary, reason, vibe, base, fixed, origin
                )
                VALUES(:title, :category, :summary, :reason, :vibe, :base, :fixed, 'local')
                """,
                DEFAULT_CATALOG,
            )

        if get_pref(conn, "disliked", None) is None:
            set_pref(conn, "disliked", DEFAULT_DISLIKED)
        if get_pref(conn, "seen", None) is None:
            set_pref(conn, "seen", [])
        if get_pref(conn, "trace_keywords", None) is None:
            set_pref(conn, "trace_keywords", [])
        if get_pref(conn, "view", None) is None:
            set_pref(conn, "view", "push")


def load_state():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, category, summary, reason, vibe, base, fixed,
                   origin, source_url, published_at, published_ts
            FROM catalog
            ORDER BY fixed DESC, id
            """
        ).fetchall()
        catalog = [dict(row) for row in rows]
        disliked = get_pref(conn, "disliked", list(DEFAULT_DISLIKED))
        seen = get_pref(conn, "seen", [])
        trace_keywords = get_pref(conn, "trace_keywords", [])
        view = get_pref(conn, "view", "push")
        locked_topics = sorted({item["category"] for item in catalog if item["fixed"]})
        categories = sorted({item["category"] for item in catalog})
        return {
            "catalog": catalog,
            "disliked": disliked,
            "seen": seen,
            "view": view,
            "lockedTopics": locked_topics or DEFAULT_LOCKED,
            "categories": categories,
            "onlineUpdatedAt": get_pref(conn, "online_updated_at", 0),
            "traceKeywords": trace_keywords,
        }


def score_item(item, disliked, seen):
    score = float(item["base"])
    if item["category"] in disliked:
        score -= 34
    if item["title"] in seen:
        score -= 18
    if item.get("origin") == "online":
        age_hours = max(0, (time.time() - float(item.get("published_ts") or 0)) / 3600)
        score += 26 * math.exp(-age_hours / 48)
    else:
        score += 4
    score += max(0, 10 - len(disliked) * 2)
    return score


def build_feed(state, batch_index=0):
    catalog = state["catalog"]
    disliked = set(state["disliked"])
    seen = set(state["seen"])
    batch = KEYWORD_BATCHES[batch_index % len(KEYWORD_BATCHES)]
    target_keywords = batch["keywords"]

    available = [item for item in catalog if item["category"] not in disliked]
    ranked = sorted(
        available,
        key=lambda item: score_item(item, disliked, seen),
        reverse=True,
    )
    feed = []
    used_categories = set()

    for keyword in target_keywords:
        matches = [item for item in ranked if item["category"] == keyword]
        if matches:
            feed.append(matches[0])
            used_categories.add(keyword)

    for item in ranked:
        if len(feed) >= len(target_keywords):
            break
        if item not in feed and item["category"] not in used_categories:
            feed.append(item)
            used_categories.add(item["category"])

    exploration = min(78, 34 + len(disliked) * 4 + min(16, len(seen) * 2))
    familiar = 100 - exploration
    return {"items": feed, "model": {"familiar": familiar, "exploration": exploration}}


def build_trace(state, batch_index=0):
    feed = build_feed(state, batch_index)["items"]
    seen = state["seen"]
    disliked = state["disliked"]

    cards = []
    for item in feed:
        cards.append(
            {
                "title": item["title"],
                "copy": "主题：{category}。{summary} {reason}".format(
                    category=item["category"],
                    summary=item["summary"],
                    reason=item["reason"],
                ),
            }
        )

    if disliked:
        cards.append(
            {
                "title": "你没看的方向",
                "copy": "已经划掉 {items}。下一轮会尽量绕开这些主题，去找更近的内容。".format(
                    items="、".join(disliked[:3])
                ),
            }
        )
    else:
        cards.append(
            {
                "title": "你还没设边界",
                "copy": "先点掉几个不想看的方向，后面的内容会更像你真正想看的那一类。",
            }
        )

    if seen:
        cards.append(
            {
                "title": "你看过的痕迹",
                "copy": "你已经点过 {count} 条，系统会把这些主题记下来，后面优先靠近它们。".format(
                    count=len(seen)
                ),
            }
        )
    else:
        cards.append(
            {
                "title": "这一轮的感觉",
                "copy": "现在先从流行乐、羽毛球这类生活兴趣开始，在线内容会沿着相邻兴趣继续展开。",
            }
        )

    return cards[:4]


def keyword_batch(index=0):
    batch = KEYWORD_BATCHES[index % len(KEYWORD_BATCHES)]
    return {
        "index": index % len(KEYWORD_BATCHES),
        "total": len(KEYWORD_BATCHES),
        "name": batch["name"],
        "source": batch["source"],
        "keywords": batch["keywords"],
    }


def boundary_batch(index=0):
    batch = BOUNDARY_BATCHES[index % len(BOUNDARY_BATCHES)]
    return {
        "index": index % len(BOUNDARY_BATCHES),
        "total": len(BOUNDARY_BATCHES),
        "name": batch["name"],
        "keywords": batch["keywords"],
    }


def trace_keyword_map(state):
    keywords = state.get("traceKeywords", [])
    return {
        "name": "已看过的关键词",
        "source": f"只增不减 · 共 {len(keywords)} 个",
        "keywords": keywords,
    }


def load_template():
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def guess_mime(path):
    suffix = path.suffix.lower()
    return {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".json": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }.get(suffix, "application/octet-stream")


def serve_static(handler, path):
    root = STATIC_DIR.resolve()
    target = (STATIC_DIR / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        handler._json({"error": "bad path"}, 400)
        return
    if not target.exists() or not target.is_file():
        handler._json({"error": "not found"}, 404)
        return
    handler._send(200, guess_mime(target), target.read_bytes())


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "ActiveMapDB/1.0"

    def log_message(self, format, *args):
        return

    def _send(self, status=200, content_type="text/plain; charset=utf-8", body=b""):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200):
        self._send(status, "application/json; charset=utf-8", json_bytes(payload))

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._send(200, "text/html; charset=utf-8", load_template().encode("utf-8"))
            return
        if path.startswith("/static/"):
            serve_static(self, path[len("/static/"):])
            return
        if path == "/api/bootstrap":
            state = load_state()
            params = parse_qs(urlparse(self.path).query)
            try:
                batch_index = int(params.get("batch", ["0"])[0])
            except ValueError:
                batch_index = 0
            payload = dict(state)
            payload["model"] = build_feed(state, batch_index)["model"]
            self._json(payload)
            return
        if path == "/api/feed":
            state = load_state()
            params = parse_qs(urlparse(self.path).query)
            try:
                batch_index = int(params.get("batch", ["0"])[0])
            except ValueError:
                batch_index = 0
            self._json(build_feed(state, batch_index))
            return
        if path == "/api/trace":
            state = load_state()
            params = parse_qs(urlparse(self.path).query)
            try:
                batch_index = int(params.get("batch", ["0"])[0])
            except ValueError:
                batch_index = 0
            self._json(
                {
                    "items": build_trace(state, batch_index),
                    "keywordMap": trace_keyword_map(state),
                }
            )
            return
        if path == "/api/keywords":
            params = parse_qs(urlparse(self.path).query)
            try:
                batch_index = int(params.get("batch", ["0"])[0])
            except ValueError:
                batch_index = 0
            self._json({"keywordMap": keyword_batch(batch_index)})
            return
        if path == "/api/boundaries":
            params = parse_qs(urlparse(self.path).query)
            try:
                batch_index = int(params.get("batch", ["0"])[0])
            except ValueError:
                batch_index = 0
            self._json({"boundaryMap": boundary_batch(batch_index)})
            return
        if path == "/favicon.ico":
            self._send(204, body=b"")
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, 400)
            return

        if path == "/api/view":
            view = data.get("view", "push")
            if view not in {"push", "map"}:
                self._json({"error": "invalid view"}, 400)
                return
            with connect() as conn:
                set_pref(conn, "view", view)
            self._json({"ok": True, "view": view})
            return

        if path == "/api/boundaries/toggle":
            category = (data.get("category") or "").strip()
            if not category:
                self._json({"error": "missing category"}, 400)
                return
            state = load_state()
            if category in state["lockedTopics"]:
                self._json({"error": "locked"}, 409)
                return
            disliked = set(state["disliked"])
            if category in disliked:
                disliked.remove(category)
            else:
                disliked.add(category)
            with connect() as conn:
                set_pref(conn, "disliked", sorted(disliked))
            self._json({"ok": True, "disliked": sorted(disliked)})
            return

        if path == "/api/event":
            kind = data.get("kind")
            title = (data.get("title") or "").strip()
            category = (data.get("category") or "").strip()
            if kind not in {"keep", "skip"}:
                self._json({"error": "invalid kind"}, 400)
                return
            with connect() as conn:
                conn.execute(
                    "INSERT INTO events(kind, title, category) VALUES(?, ?, ?)",
                    (kind, title, category),
                )
                seen = get_pref(conn, "seen", [])
                if title and title not in seen:
                    seen.insert(0, title)
                seen = seen[:12]
                set_pref(conn, "seen", seen)

                disliked = set(get_pref(conn, "disliked", list(DEFAULT_DISLIKED)))
                if kind == "keep" and category in disliked:
                    disliked.remove(category)
                elif kind == "skip" and category:
                    disliked.add(category)
                set_pref(conn, "disliked", sorted(disliked))

                trace_keywords = get_pref(conn, "trace_keywords", [])
                if category and category not in trace_keywords:
                    trace_keywords.append(category)
                set_pref(conn, "trace_keywords", trace_keywords)

            self._json({"ok": True})
            return

        if path == "/api/catalog":
            title = (data.get("title") or "").strip()
            category = (data.get("category") or "").strip()
            summary = (data.get("summary") or "").strip()
            reason = (data.get("reason") or "").strip()
            vibe = (data.get("vibe") or "").strip()
            try:
                base = int(data.get("base", 80))
            except (TypeError, ValueError):
                base = 80

            if not all([title, category, summary, reason, vibe]):
                self._json({"error": "missing fields"}, 400)
                return

            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO catalog(title, category, summary, reason, vibe, base, fixed)
                    VALUES(?, ?, ?, ?, ?, ?, 0)
                    """,
                    (title, category, summary, reason, vibe, base),
                )

            self._json({"ok": True})
            return

        self._json({"error": "not found"}, 404)


def main():
    init_db()

    threading.Thread(
        target=refresh_online_content,
        kwargs={"force": True},
        daemon=True,
    ).start()

    def refresh_loop():
        while True:
            time.sleep(CONTENT_REFRESH_INTERVAL)
            refresh_online_content(force=True)

    threading.Thread(target=refresh_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8123), Handler)
    threading.Timer(0.8, lambda: webbrowser.open_new("http://127.0.0.1:8123")).start()
    print("Serving on http://127.0.0.1:8123")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

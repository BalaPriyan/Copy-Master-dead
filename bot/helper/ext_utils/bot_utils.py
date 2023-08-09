from asyncio import (create_subprocess_exec, create_subprocess_shell,
                     run_coroutine_threadsafe, sleep)
from asyncio.subprocess import PIPE
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from html import escape
from re import match
from time import time
from uuid import uuid4
from psutil import cpu_percent, disk_usage, virtual_memory
from pyrogram.types import BotCommand
from pyrogram.handlers import CallbackQueryHandler
from pyrogram.filters import regex
from aiohttp import ClientSession
from aiohttp import ClientSession
from psutil import virtual_memory, cpu_percent, disk_usage
from aiofiles.os import remove as aioremove, path as aiopath, mkdir
from psutil import disk_usage, disk_io_counters, Process, cpu_percent, swap_memory, cpu_count, cpu_freq, getloadavg, virtual_memory, net_io_counters, boot_time

from bot.version import get_version
from bot import (bot, bot_loop, bot_name, botStartTime, config_dict, download_dict,
                 download_dict_lock, extra_buttons, user_data)
from bot.helper.ext_utils.shortener import short_url
from bot.helper.ext_utils.telegraph_helper import telegraph
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.themes import BotTheme

THREADPOOL      = ThreadPoolExecutor(max_workers=1000)
MAGNET_REGEX    = r'^magnet:\?.*xt=urn:(btih|btmh):[a-zA-Z0-9]*\s*'
URL_REGEX       = r'^(?!\/)(rtmps?:\/\/|mms:\/\/|rtsp:\/\/|https?:\/\/|ftp:\/\/)?([^\/:]+:[^\/@]+@)?(www\.)?(?=[^\/:\s]+\.[^\/:\s]+)([^\/:\s]+\.[^\/:\s]+)(:\d+)?(\/[^#\s]*[\s\S]*)?(\?[^#\s]*)?(#.*)?$'
SIZE_UNITS      = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
STATUS_START    = 0
PAGES           = 1
PAGE_NO         = 1

class MirrorStatus:
    STATUS_UPLOADING    = "Uploading"
    STATUS_DOWNLOADING  = "Downloading"
    STATUS_CLONING      = "Cloning"
    STATUS_QUEUEDL      = "Queued Download"
    STATUS_QUEUEUP      = "Queued Upload"
    STATUS_PAUSED       = "Paused"
    STATUS_ARCHIVING    = "Archiving"
    STATUS_EXTRACTING   = "Extracting"
    STATUS_SPLITTING    = "Spliting"
    STATUS_CHECKING     = "CheckingUp"
    STATUS_SEEDING      = "Seeding"

class setInterval:
    def __init__(self, interval, action):
        self.interval   = interval
        self.action     = action
        self.task       = bot_loop.create_task(self.__set_interval())

    async def __set_interval(self):
        while True:
            await sleep(self.interval)
            await self.action()

    def cancel(self):
        self.task.cancel()


def get_readable_file_size(size_in_bytes):
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1
    return f'{size_in_bytes:.2f}{SIZE_UNITS[index]}' if index > 0 else f'{size_in_bytes}B'


async def getDownloadByGid(gid):
    async with download_dict_lock:
        return next((dl for dl in download_dict.values() if dl.gid() == gid), None)


async def getAllDownload(req_status, user_id=None):
    dls = []
    async with download_dict_lock:
        for dl in list(download_dict.values()):
            if user_id and user_id != dl.message.from_user.id:
                continue
            status = dl.status()
            if req_status in ['all', status]:
                dls.append(dl)
    return dls


def bt_selection_buttons(id_, isCanCncl=True):
    gid = id_[:12] if len(id_) > 20 else id_
    pincode = ''.join([n for n in id_ if n.isdigit()][:4])
    buttons = ButtonMaker()
    BASE_URL = config_dict['BASE_URL']
    if config_dict['WEB_PINCODE']:
        buttons.ubutton("Select Files", f"{BASE_URL}/app/files/{id_}")
        buttons.ibutton("Pincode", f"btsel pin {gid} {pincode}")
    else:
        buttons.ubutton(
            "Select Files", f"{BASE_URL}/app/files/{id_}?pin_code={pincode}")
    if isCanCncl:
        buttons.ibutton("Cancel", f"btsel rm {gid} {id_}")
    buttons.ibutton("Done Selecting", f"btsel done {gid} {id_}")
    return buttons.build_menu(2)


async def get_telegraph_list(telegraph_content):
    path = [(await telegraph.create_page(title='Drive Search', content=content))["path"] for content in telegraph_content]
    if len(path) > 1:
        await telegraph.edit_telegraph(path, telegraph_content)
    buttons = ButtonMaker()
    buttons.ubutton("🔎 VIEW", f"https://graph.org/{path[0]}", 'header')
    buttons = extra_btns(buttons)
    return buttons.build_menu(1)


def get_progress_bar_string(pct):
    if isinstance(pct, str):
        pct = float(pct.strip('%'))
    p = min(max(pct, 0), 100)
    cFull = int(p // 10)
    p_str = '⬢' * cFull
    p_str += '⬡' * (10 - cFull)
    return f"{p_str}"



def get_readable_message():
    msg = ""
    button = None
    STATUS_LIMIT = config_dict['STATUS_LIMIT']
    tasks = len(download_dict)

    globals()['PAGES'] = (tasks + STATUS_LIMIT - 1) // STATUS_LIMIT
    if PAGE_NO > PAGES and PAGES != 0:
        globals()['STATUS_START'] = STATUS_LIMIT * (PAGES - 1)
        globals()['PAGE_NO'] = PAGES

    for download in list(download_dict.values())[STATUS_START:STATUS_LIMIT+STATUS_START]:

        tag = download.message.from_user.mention
        if reply_to := download.message.reply_to_message:
            tag = reply_to.from_user.mention

        elapsed = time() - download.extra_details['startTime']
        msg += f"\n ╭ <b>File Name</b> » <i>{escape(f'{download.name()}')}</i>\n" if elapsed <= config_dict['AUTO_DELETE_MESSAGE_DURATION'] else ""
        msg += f"• <b>{download.status()}</b>"

        if download.status() not in [MirrorStatus.STATUS_SEEDING, MirrorStatus.STATUS_PAUSED,
                                     MirrorStatus.STATUS_QUEUEDL, MirrorStatus.STATUS_QUEUEUP]:

            
            msg += f"\n├ {get_progress_bar_string(download.progress())} » {download.progress()}"
            msg += f"\n├ {download.speed()}"
            msg += f"\n├ <code>Done     </code>» {download.processed_bytes()} of {download.size()}"
            msg += f"\n├ <code>ETA      </code>» {download.eta()}"
            msg += f"\n├ <code>Active   </code>» {get_readable_time(elapsed)}"
            msg += f"\n├ <code>Engine   </code>» {download.engine}"

            if hasattr(download, 'playList'):
                try:
                    if playlist:=download.playList():
                        msg += f"\n• <code>YT Count </code>» {playlist}"
                except:
                    pass

            if hasattr(download, 'seeders_num'):
                try:
                    msg += f"\n├ <code>Seeders  </code>» {download.seeders_num()}"
                    msg += f"\n├ <code>Leechers </code>» {download.leechers_num()}"
                except:
                    pass

        elif download.status() == MirrorStatus.STATUS_SEEDING:
            msg += f"\n├ <code>Size     </code>» {download.size()}"
            msg += f"\n├ <code>Speed    </code>» {download.upload_speed()}"
            msg += f"\n├ <code>Uploaded </code>» {download.uploaded_bytes()}"
            msg += f"\n├ <code>Ratio    </code>» {download.ratio()}"
            msg += f"\n├ <code>Time     </code>» {download.seeding_time()}"
        else:
            msg += f"\n├ <code>Size     </code>» {download.size()}"

        if config_dict['DELETE_LINKS']:
            msg += f"\n├ <code>Task     </code>» {download.extra_details['mode']}"
        else:
            msg += f"\n├ <code>Task     </code>» <a href='{download.message.link}'>{download.extra_details['mode']}</a>"

        msg += f"\n╰ <code>User     </code>» {tag}"
        msg += f"\n☠︎ /{BotCommands.CancelMirror}_{download.gid()}\n\n"

    if len(msg) == 0:
        return None, None

    def convert_speed_to_bytes_per_second(spd):
        if 'K' in spd:
            return float(spd.split('K')[0]) * 1024
        elif 'M' in spd:
            return float(spd.split('M')[0]) * 1048576
        else:
            return 0

    dl_speed = 0
    up_speed = 0
    for download in download_dict.values():
        tstatus = download.status()
        spd = download.speed() if tstatus != MirrorStatus.STATUS_SEEDING else download.upload_speed()
        speed_in_bytes_per_second = convert_speed_to_bytes_per_second(spd)
        if tstatus == MirrorStatus.STATUS_DOWNLOADING:
            dl_speed += speed_in_bytes_per_second
        elif tstatus == MirrorStatus.STATUS_UPLOADING or tstatus == MirrorStatus.STATUS_SEEDING:
            up_speed += speed_in_bytes_per_second


    if tasks <= STATUS_LIMIT:
        buttons = ButtonMaker()
        buttons.ibutton("BOT INFO", "stats")
        button = buttons.build_menu(1)


    if tasks > STATUS_LIMIT:
        buttons = ButtonMaker()
        buttons.ibutton("⫷", "status pre")
        buttons.ibutton(f"{PAGE_NO}/{PAGES}", "stats")
        buttons.ibutton("⫸", "status nex")
        button = buttons.build_menu(3)

    msg += f"<b>____________________________</b>"
    msg += f"\n╭<b>DL</b>: <code>{get_readable_file_size(dl_speed)}/s</code>"
    msg += f"\n╰<b>UL</b>: <code>{get_readable_file_size(up_speed)}/s</code>"
    remaining_time = 86400 - (time() - botStartTime)
    res_time = '☠︎ ANYTIME ☠︎' if remaining_time <= 0 else get_readable_time(remaining_time)
    if remaining_time <= 3600:
        msg += f"\n╰<b>Bot Restarts In:</b> <code>{res_time}</code>"
    return msg, button


async def fstats(_, query):
    acti = len(download_dict)
    free = config_dict['QUEUE_ALL'] - acti
    inqu, dwld, upld, splt, clon, arch, extr, seed = [0] * 8
    fdisk = get_readable_file_size(disk_usage(config_dict["DOWNLOAD_DIR"]).free)
    uptm = time() - botStartTime
    for download in download_dict.values():
        status = download.status()
        if status in MirrorStatus.STATUS_QUEUEDL or status in MirrorStatus.STATUS_QUEUEUP:
            inqu += 1
        elif status == MirrorStatus.STATUS_DOWNLOADING:
            dwld += 1
        elif status == MirrorStatus.STATUS_UPLOADING:
            upld += 1
        elif status == MirrorStatus.STATUS_SPLITTING:
            splt += 1
        elif status == MirrorStatus.STATUS_CLONING:
            clon += 1
        elif status == MirrorStatus.STATUS_ARCHIVING:
            arch += 1
        elif status == MirrorStatus.STATUS_EXTRACTING:
            extr += 1
        elif status == MirrorStatus.STATUS_SEEDING:
            seed += 1

    stat = f'\n⌬<_____Bot Info_____>\n\n'\
           f'\n├Active: {acti}, Free: {free}, Queued: {inqu}\n\n' \
           f'\n├Download: {dwld}, Upload: {upld}, Seed: {seed}\n\n' \
           f'\n├Split: {splt}, Clone: {clon}\n\n' \
           f'\n├Zip: {arch}, UnZip: {extr}\n\n' \
           f'\n├Free Disk: {fdisk} ' \
           f'\n╰Uptime: {get_readable_time(uptm)}'
    await query.answer(stat, show_alert=True)


async def turn_page(data):
    STATUS_LIMIT = config_dict['STATUS_LIMIT']
    global STATUS_START, PAGE_NO, PAGES
    async with download_dict_lock:
        if data[1] == "nex" and PAGE_NO == PAGES:
            PAGE_NO = 1
        elif data[1] == "nex" and PAGE_NO < PAGES:
            PAGE_NO += 1
        elif data[1] == "pre" and PAGE_NO == 1:
            PAGE_NO = PAGES
        elif data[1] == "pre" and PAGE_NO > 1:
            PAGE_NO -= 1
        if data[1] != "stats":
            STATUS_START = (PAGE_NO - 1) * STATUS_LIMIT


def get_readable_time(seconds):
    periods = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name}'
    return result


def is_magnet(url):
    return bool(match(MAGNET_REGEX, url))


def is_url(url):
    return bool(match(URL_REGEX, url))


def is_gdrive_link(url):
    return "drive.google.com" in url


def is_telegram_link(url):
    return url.startswith(('https://t.me/', 'tg://openmessage?user_id='))


def is_share_link(url: str):
    if 'gdtot' in url:
        regex = r'(https?:\/\/.+\.gdtot\..+\/file\/\d+)'
    else:
        regex = r'(https?:\/\/(\S+)\..+\/file\/\S+)'
    return bool(match(regex, url))


def is_mega_link(url):
    return "mega.nz" in url or "mega.co.nz" in url


def is_rclone_path(path):
    return bool(match(r'^(mrcc:)?(?!magnet:)(?![- ])[a-zA-Z0-9_\. -]+(?<! ):(?!.*\/\/).*$|^rcl$', path))


def get_mega_link_type(url):
    return "folder" if "folder" in url or "/#F!" in url else "file"

def arg_parser(items, arg_base):
    if not items:
        return arg_base
    bool_arg_set = {
                    '-b', '-bulk', 
                    '-e', '-uz', '-unzip', 
                    '-z', '-zip', 
                    '-s', '-select', 
                    '-j', '-join', 
                    '-d', '-seed'
                    }
    t = len(items)
    m = 0
    arg_start = -1
    while m + 1 <= t:
        part = items[m].strip()
        if part in arg_base:
            if arg_start == -1:
                arg_start = m
            if m + 1 == t and part in bool_arg_set or part in [
                                                                '-s', '-select', 
                                                                '-j', '-join'
                                                            ]:
                arg_base[part] = True
            else:
                sub_list = []
                for j in range(m + 1, t):
                    item = items[j].strip()
                    if item in arg_base:
                        if part in bool_arg_set and not sub_list:
                            arg_base[part] = True
                        break
                    sub_list.append(item.strip())
                    m += 1
                if sub_list:
                    arg_base[part] = " ".join(sub_list)
        m += 1
    link = []
    if items[0].strip() not in arg_base:
        if arg_start == -1:
            link.extend(item.strip() for item in items)
        else:
            link.extend(items[r].strip() for r in range(arg_start))
        if link:
            arg_base['link'] = " ".join(link)
    return arg_base


async def get_content_type(url):
    try:
        async with ClientSession(trust_env=True) as session:
            async with session.get(url, verify_ssl=False) as response:
                return response.headers.get('Content-Type')
    except:
        return None


def update_user_ldata(id_, key, value):
    if not key and not value:
        user_data[id_] = {}
        return
    user_data.setdefault(id_, {})
    user_data[id_][key] = value


def extra_btns(buttons):
    if extra_buttons:
        for btn_name, btn_url in extra_buttons.items():
            buttons.ubutton(btn_name, btn_url)
    return buttons


async def check_user_tasks(user_id, maxtask):
    downloading_tasks   = await getAllDownload(MirrorStatus.STATUS_DOWNLOADING, user_id)
    uploading_tasks     = await getAllDownload(MirrorStatus.STATUS_UPLOADING, user_id)
    cloning_tasks       = await getAllDownload(MirrorStatus.STATUS_CLONING, user_id)
    splitting_tasks     = await getAllDownload(MirrorStatus.STATUS_SPLITTING, user_id)
    archiving_tasks     = await getAllDownload(MirrorStatus.STATUS_ARCHIVING, user_id)
    extracting_tasks    = await getAllDownload(MirrorStatus.STATUS_EXTRACTING, user_id)
    queuedl_tasks       = await getAllDownload(MirrorStatus.STATUS_QUEUEDL, user_id)
    queueup_tasks       = await getAllDownload(MirrorStatus.STATUS_QUEUEUP, user_id)
    total_tasks         = downloading_tasks + uploading_tasks + cloning_tasks + splitting_tasks + archiving_tasks + extracting_tasks + queuedl_tasks + queueup_tasks
    return len(total_tasks) >= maxtask


def checking_access(user_id, button=None):
    if not config_dict['TOKEN_TIMEOUT']:
        return None, button
    user_data.setdefault(user_id, {})
    data = user_data[user_id]
    expire = data.get('time')
    isExpired = (expire is None or expire is not None and (
        time() - expire) > config_dict['TOKEN_TIMEOUT'])
    if isExpired:
        token = data['token'] if expire is None and 'token' in data else str(
            uuid4())
        if expire is not None:
            del data['time']
        data['token'] = token
        user_data[user_id].update(data)
        if button is None:
            button = ButtonMaker()
        button.ubutton('Get New Token', short_url(f'https://telegram.me/{bot_name}?start={token}'))
        return 'Your <b>Token</b> is expired. Get a new one.', button
    return None, button


async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    stdout = stdout.decode().strip()
    stderr = stderr.decode().strip()
    return stdout, stderr, proc.returncode


def new_task(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return bot_loop.create_task(func(*args, **kwargs))
    return wrapper


async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(THREADPOOL, pfunc)
    return await future if wait else future


def async_to_sync(func, *args, wait=True, **kwargs):
    future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
    return future.result() if wait else future


def new_thread(func):
    @wraps(func)
    def wrapper(*args, wait=False, **kwargs):
        future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
        return future.result() if wait else future
    return wrapper

async def compare_versions(v1, v2):
    v1_parts = [int(part) for part in v1[1:-2].split('.')]
    v2_parts = [int(part) for part in v2[1:-2].split('.')]
    for i in range(3):
        v1_part, v2_part = v1_parts[i], v2_parts[i]
        if v1_part < v2_part:
            return "New Version Update is Available! Check Now!"
        elif v1_part > v2_part:
            return "More Updated! Kindly Contribute in Official"
    return "Already up to date with latest version"



async def get_stats(event, key="home"):
    user_id = event.from_user.id
    btns = ButtonMaker()
    btns.ibutton('Back', f'wzmlx {user_id} stats home')
    if key == "home":
        btns = ButtonMaker()
        btns.ibutton('Bot Stats', f'wzmlx {user_id} stats stbot')
        btns.ibutton('OS Stats', f'wzmlx {user_id} stats stsys')
        btns.ibutton('Repo Stats', f'wzmlx {user_id} stats strepo')
        btns.ibutton('Bot Limits', f'wzmlx {user_id} stats botlimits')
        msg = "⌬ <b><i>Bot & OS Statistics!</i></b>"
    elif key == "stbot":
        sysTime     = get_readable_time(time() - boot_time())
        botTime     = get_readable_time(time() - botStartTime)
        remaining_time = 86400 - (time() - botStartTime)
        res_time = '⚠️ Soon ⚠️' if remaining_time <= 0 else get_readable_time(remaining_time)
        total, used, free, disk = disk_usage('/')
        swap = swap_memory()
        memory = virtual_memory()
        total       = get_readable_file_size(total)
        used        = get_readable_file_size(used)
        free        = get_readable_file_size(free)
        sent        = get_readable_file_size(net_io_counters().bytes_sent)
        recv        = get_readable_file_size(net_io_counters().bytes_recv)
        tb          = get_readable_file_size(net_io_counters().bytes_sent + net_io_counters().bytes_recv)
        cpuUsage    = cpu_percent(interval=1)
        v_core      = cpu_count(logical=True) - cpu_count(logical=False)
        memory      = virtual_memory()
        swap        = swap_memory()
        mem_p       = memory.percent
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io is not None:
                disk_read = get_readable_file_size(disk_io.read_bytes) + f" ({get_readable_time(disk_io.read_time / 1000)})"
                disk_write = get_readable_file_size(disk_io.write_bytes) + f" ({get_readable_time(disk_io.write_time / 1000)})"
            else:
                disk_read = "N/A"
                disk_write = "N/A"
        except Exception as e:
            disk_read = "Error"
            disk_write = "Error"
        if config_dict['WZMLX']: 
                msg = BotTheme('BOT_STATS',  
                      bot_uptime=get_readable_time(time() - botStartTime),
                      ram_bar=get_progress_bar_string(memory.percent),
                      ram=memory.percent,
                      ram_u=get_readable_file_size(memory.used),
                      ram_f=get_readable_file_size(memory.available),
                      ram_t=get_readable_file_size(memory.total),
                      swap_bar=get_progress_bar_string(swap.percent),
                      swap=swap.percent,
                      swap_u=get_readable_file_size(swap.used),
                      swap_f=get_readable_file_size(swap.free),
                      swap_t=get_readable_file_size(swap.total),
                      disk=disk,
                      disk_bar=get_progress_bar_string(disk),
                      disk_read=disk_read,
                      disk_write=disk_write,
                      disk_t=get_readable_file_size(total),
                      disk_u=get_readable_file_size(used),
                      disk_f=get_readable_file_size(free),
                  )
        else:
                  msg = f'⌬<b><i><u>Bot Statistics</u></i></b>\n\n'\
                        f'╭<code>CPU  : </code>{get_progress_bar_string(cpuUsage)} {cpuUsage}%\n' \
                        f'├<code>RAM  : </code>{get_progress_bar_string(mem_p)} {mem_p}%\n' \
                        f'├<code>SWAP : </code>{get_progress_bar_string(swap.percent)} {swap.percent}%\n' \
                        f'╰<code>DISK : </code>{get_progress_bar_string(disk)} {disk}%\n\n' \
                        f'●<code>Bot Uptime      : </code> {botTime}\n' \
                        f'●<code>BOT Restart     : </code> {res_time}\n\n' \
                        f'●<code>Uploaded        : </code> {sent}\n' \
                        f'●<code>Downloaded      : </code> {recv}\n' \
                        f'●<code>Total Bandwidth : </code> {tb}'
    elif key == "stsys":
        cpuUsage = cpu_percent(interval=0.5)
        if config_dict['WZMLX']: 
            msg = BotTheme('SYS_STATS',
                           os_uptime=get_readable_time(time() - boot_time()),
                           os_version=platform.version(),
                           os_arch=platform.platform(),
                           up_data=get_readable_file_size(net_io_counters().bytes_sent),
                           dl_data=get_readable_file_size(net_io_counters().bytes_recv),
                           pkt_sent=str(net_io_counters().packets_sent)[:-3],
                           pkt_recv=str(net_io_counters().packets_recv)[:-3],
                           tl_data=get_readable_file_size(net_io_counters().bytes_recv + net_io_counters().bytes_sent),
                           cpu=cpuUsage,
                           cpu_bar=get_progress_bar_string(cpuUsage),
                           cpu_freq=f"{cpu_freq(percpu=False).current / 1000:.2f} GHz" if cpu_freq() else "Access Denied",
                           sys_load="%, ".join(str(round((x / cpu_count() * 100), 2)) for x in getloadavg()) + "%, (1m, 5m, 15m)",
                           p_core=cpu_count(logical=False),
                           v_core=cpu_count(logical=True) - cpu_count(logical=False),
                           total_core=cpu_count(logical=True),
                           cpu_use=len(Process().cpu_affinity()),
           )
        else:
           msg = f'⌬<b><i><u>System Statistics</u></i></b>\n\n'\
                 f'╭<b>System Uptime:</b> <code>{sysTime}</code>\n' \
                 f'├<b>P-Core(s):</b> <code>{cpu_count(logical=False)}</code> | ' \
                 f'├<b>V-Core(s):</b> <code>{v_core}</code>\n' \
                 f'╰<b>Frequency:</b> <code>{cpu_freq(percpu=False).current / 1000:.2f} GHz</code>\n\n' \
                 f'●<b>CPU:</b> {get_progress_bar_string(cpuUsage)}<code> {cpuUsage}%</code>\n' \
                 f'╰<b>CPU Total Core(s):</b> <code>{cpu_count(logical=True)}</code>\n\n' \
                 f'●<b>RAM:</b> {get_progress_bar_string(mem_p)}<code> {mem_p}%</code>\n' \
                 f'╰<b>Total:</b> <code>{get_readable_file_size(memory.total)}</code> | ' \
                 f'●<b>Free:</b> <code>{get_readable_file_size(memory.available)}</code>\n\n' \
                 f'●<b>SWAP:</b> {get_progress_bar_string(swap.percent)}<code> {swap.percent}%</code>\n' \
                 f'╰<b>Total</b> <code>{get_readable_file_size(swap.total)}</code> | ' \
                 f'●<b>Free:</b> <code>{get_readable_file_size(swap.free)}</code>\n\n' \
                 f'●<b>DISK:</b> {get_progress_bar_string(disk)}<code> {disk}%</code>\n' \
                 f'╰<b>Total:</b> <code>{total}</code> | <b>Free:</b> <code>{free}</code>'
    elif key == "strepo":
        last_commit, changelog = 'No Data', 'N/A'
        if await aiopath.exists('.git'):
            last_commit = (await cmd_exec("git log -1 --pretty='%cd ( %cr )' --date=format-local:'%d/%m/%Y'", True))[0]
            version     = (await cmd_exec("git describe --abbrev=0 --tags", True))[0]
            changelog = (await cmd_exec("git log -1 --pretty=format:'<code>%s</code> <b>By</b> %an'", True))[0]
        official_v = (await cmd_exec("curl -o latestversion.py https://raw.githubusercontent.com/weebzone/WZML-X/master/bot/version.py -s && python3 latestversion.py && rm latestversion.py", True))[0]
        if config_dict['WZMLX']:
           msg = BotTheme('REPO_STATS',
                          last_commit=last_commit,
                          bot_version=get_version(),
                          lat_version=official_v,
                          commit_details=changelog,
                          remarks=await compare_versions(get_version(), official_v),
           )
        else:
           msg = f'⌬<b><i><u>Repo Info</u></i></b>\n\n' \
                 f'╭<code>Updated   : </code> {last_commit}\n' \
                 f'├<code>Version   : </code> {version}\n' \
                 f'╰<code>Changelog : </code> {change_log}'
    elif key == "botlimits":
        if config_dict['WZMLX']:
           msg = BotTheme('BOT_LIMITS',
                          DL = ('∞' if (val := config_dict['DIRECT_LIMIT']) == '' else val),
                          TL = ('∞' if (val := config_dict['TORRENT_LIMIT']) == '' else val),
                          GL = ('∞' if (val := config_dict['GDRIVE_LIMIT']) == '' else val),
                          YL = ('∞' if (val := config_dict['YTDLP_LIMIT']) == '' else val),
                          PL = ('∞' if (val := config_dict['PLAYLIST_LIMIT']) == '' else val),
                          CL = ('∞' if (val := config_dict['CLONE_LIMIT']) == '' else val),
                          ML = ('∞' if (val := config_dict['MEGA_LIMIT']) == '' else val),
                          LL = ('∞' if (val := config_dict['LEECH_LIMIT']) == '' else val),
                          TV  = ('Disabled' if (val := config_dict['TOKEN_TIMEOUT']) == '' else get_readable_time(val)),
                          UTI = ('Disabled' if (val := config_dict['USER_TIME_INTERVAL']) == 0 else get_readable_time(val)),
                          UT = ('∞' if (val := config_dict['USER_MAX_TASKS']) == '' else val),
                          BT = ('∞' if (val := config_dict['BOT_MAX_TASKS']) == '' else val),
           )
        else:
          DIR = 'Unlimited' if config_dict['DIRECT_LIMIT']    == '' else config_dict['DIRECT_LIMIT']
          YTD = 'Unlimited' if config_dict['YTDLP_LIMIT']     == '' else config_dict['YTDLP_LIMIT']
          GDL = 'Unlimited' if config_dict['GDRIVE_LIMIT']    == '' else config_dict['GDRIVE_LIMIT']
          TOR = 'Unlimited' if config_dict['TORRENT_LIMIT']   == '' else config_dict['TORRENT_LIMIT']
          CLL = 'Unlimited' if config_dict['CLONE_LIMIT']     == '' else config_dict['CLONE_LIMIT']
          MGA = 'Unlimited' if config_dict['MEGA_LIMIT']      == '' else config_dict['MEGA_LIMIT']
          TGL = 'Unlimited' if config_dict['LEECH_LIMIT']     == '' else config_dict['LEECH_LIMIT']
          UMT = 'Unlimited' if config_dict['USER_MAX_TASKS']  == '' else config_dict['USER_MAX_TASKS']
          BMT = 'Unlimited' if config_dict['QUEUE_ALL']       == '' else config_dict['QUEUE_ALL']

          msg = f'⌬<b><i><u>Bot Limitations</u></i></b>\n' \
                f'╭<code>Torrent   : {TOR}</code> <b>GB</b>\n' \
                f'├<code>G-Drive   : {GDL}</code> <b>GB</b>\n' \
                f'├<code>Yt-Dlp    : {YTD}</code> <b>GB</b>\n' \
                f'├<code>Direct    : {DIR}</code> <b>GB</b>\n' \
                f'├<code>Clone     : {CLL}</code> <b>GB</b>\n' \
                f'├<code>Leech     : {TGL}</code> <b>GB</b>\n' \
                f'╰<code>MEGA      : {MGA}</code> <b>GB</b>\n\n' \
                f'╭<code>User Tasks: {UMT}</code>\n' \
                f'╰<code>Bot Tasks : {BMT}</code>'
          
    btns.ibutton('Close', f'wzmlx {user_id} close')
    return msg, btns.build_menu(2)



async def set_commands(client):
    if config_dict['SET_COMMANDS']:
        await client.set_bot_commands([
            BotCommand(f'{BotCommands.MirrorCommand[0]}', f'or /{BotCommands.MirrorCommand[1]} Mirror'),
            BotCommand(f'{BotCommands.LeechCommand[0]}', f'or /{BotCommands.LeechCommand[1]} Leech'),
            BotCommand(f'{BotCommands.QbMirrorCommand[0]}', f'or /{BotCommands.QbMirrorCommand[1]} Mirror torrent using qBittorrent'),
            BotCommand(f'{BotCommands.QbLeechCommand[0]}', f'or /{BotCommands.QbLeechCommand[1]} Leech torrent using qBittorrent'),
            BotCommand(f'{BotCommands.YtdlCommand[0]}', f'or /{BotCommands.YtdlCommand[1]} Mirror yt-dlp supported link'),
            BotCommand(f'{BotCommands.YtdlLeechCommand[0]}', f'or /{BotCommands.YtdlLeechCommand[1]} Leech through yt-dlp supported link'),
            BotCommand(f'{BotCommands.CloneCommand}', 'Copy file/folder to Drive'),
            BotCommand(f'{BotCommands.CountCommand}', '[drive_url]: Count file/folder of Google Drive.'),
            BotCommand(f'{BotCommands.StatusCommand[0]}', f'or /{BotCommands.StatusCommand[1]} Get mirror status message'),
            BotCommand(f'{BotCommands.StatsCommand[0]}', f'{BotCommands.StatsCommand[1]} Check bot stats'),
            BotCommand(f'{BotCommands.BtSelectCommand}', 'Select files to download only torrents'),
            BotCommand(f'{BotCommands.CategorySelect}', 'Select category to upload only mirror'),
            BotCommand(f'{BotCommands.CancelMirror}', 'Cancel a Task'),
            BotCommand(f'{BotCommands.CancelAllCommand[0]}', f'Cancel all tasks which added by you or {BotCommands.CancelAllCommand[1]} to in bots.'),
            BotCommand(f'{BotCommands.ListCommand}', 'Search in Drive'),
            BotCommand(f'{BotCommands.SearchCommand}', 'Search in Torrent'),
            BotCommand(f'{BotCommands.UserSetCommand}', 'Users settings'),
            BotCommand(f'{BotCommands.HelpCommand}', 'Get detailed help'),
        ])

bot.add_handler(CallbackQueryHandler(fstats, filters=regex("^stats")))

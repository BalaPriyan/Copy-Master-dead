from asyncio import create_subprocess_exec, gather
from os import execl as osexecl
from signal import SIGINT, signal
from sys import executable
from time import time, monotonic
from uuid import uuid4

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath
from aiofiles.os import remove as aioremove
from psutil import (boot_time, cpu_count, cpu_percent, cpu_freq, disk_usage,
                    net_io_counters, swap_memory, virtual_memory)
from pyrogram.filters import command, regex
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from bot import (DATABASE_URL, INCOMPLETE_TASK_NOTIFIER, LOGGER,
                 STOP_DUPLICATE_TASKS, Interval, QbInterval, bot, botStartTime,
                 config_dict, scheduler, user_data)
from bot.helper.listeners.aria2_listener import start_aria2_listener

from .helper.ext_utils.bot_utils import (cmd_exec, get_readable_file_size, get_readable_time, new_thread, set_commands, sync_to_async, get_progress_bar_string, get_stats)
from .helper.ext_utils.db_handler import DbManger
from .helper.ext_utils.fs_utils import clean_all, exit_clean_up, start_cleanup
from .helper.telegram_helper.button_build import ButtonMaker
from .helper.telegram_helper.bot_commands import BotCommands
from .helper.telegram_helper.filters import CustomFilters
from .helper.themes import BotTheme
from .helper.telegram_helper.message_utils import (editMessage, sendFile,
                                                   sendMessage, auto_delete_message)
from .modules import (anonymous, authorize, bot_settings, cancel_mirror,
                      category_select, clone, eval, gd_count, gd_delete,
                      gd_list, leech_del, mirror_leech, rmdb, rss,
                      shell, status, torrent_search,
                      torrent_select, users_settings, ytdlp, broadcast)

async def stats(client, message):
    msg, btns = await get_stats(message)
    await sendMessage(message, msg, btns, photo=BotTheme('PIC'))

async def start(client, message):
    buttons = ButtonMaker()
    buttons.ubutton(BotTheme('ST_BN1_NAME'), BotTheme('ST_BN1_URL'))
    buttons.ubutton(BotTheme('ST_BN2_NAME'), BotTheme('ST_BN2_URL'))
    reply_markup = buttons.build_menu(2)
    if len(message.command) > 1:
        userid = message.from_user.id
        input_token = message.command[1]
        if userid not in user_data:
            return await sendMessage(message, 'This token is not yours!\n\nKindly generate your own.')
        data = user_data[userid]
        if 'token' not in data or data['token'] != input_token:
            return await sendMessage(message, 'Token already used!\n\nKindly generate a new one.')
        data['token'] = str(uuid4())
        data['time'] = time()
        user_data[userid].update(data)
        msg = 'Token refreshed successfully!\n\n'
        msg += f'Validity: {get_readable_time(int(config_dict["TOKEN_TIMEOUT"]))}'
        return await sendMessage(message, msg)
    elif await CustomFilters.authorized(client, message):
        start_string = BotTheme('ST_MSG', help_command=f"/{BotCommands.HelpCommand}")
        await message.reply_photo(BotTheme('PIC'), caption=start_string, reply_markup=reply_markup)
    elif config_dict['DM_MODE']:
        await sendMessage(message, BotTheme('ST_BOTPM'), reply_markup=reply_markup, photo=BotTheme('PIC'))
    else:
        await sendMessage(message, BotTheme('ST_UNAUTH'), reply_markup, photo=BotTheme('PIC'))
    await DbManger().update_pm_users(message.from_user.id)


async def restart(_, message):
    restart_message = await sendMessage(message, "Restarting...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    for interval in [QbInterval, Interval]:
        if interval:
            interval[0].cancel()
    await sync_to_async(clean_all)
    proc1 = await create_subprocess_exec('pkill', '-9', '-f', '-e', 'gunicorn|buffet|openstack|render|zcl')
    proc2 = await create_subprocess_exec('python3', 'update.py')
    await gather(proc1.wait(), proc2.wait())
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")
    osexecl(executable, executable, "-m", "bot")

@new_thread
async def ping(_, message):
    start_time = monotonic()
    reply = await sendMessage(message, "Starting Ping")
    end_time = monotonic()
    ping_time = int((end_time - start_time) * 1000)
    await editMessage(reply, f'{ping_time} ms')

async def log(_, message):
    await sendFile(message, 'log.txt')


async def bot_help(client, message):
    buttons = ButtonMaker()
    user_id = message.from_user.id
    buttons.ibutton('Basic', f'{user_id} guide basic')
    buttons.ibutton('Users', f'{user_id} guide users')
    buttons.ibutton('Mics', f'{user_id} guide miscs')
    buttons.ibutton('Owner & Sudos', f'{user_id} guide admin')
    buttons.ibutton('Close', f'{user_id} close')
    await sendMessage(message, "⚙ <b><i>Help Guide Menu!</i></b>\n\n<b>NOTE: <i>Click on any CMD to see more minor detalis.</i></b>", buttons.build_menu(2))
    await auto_delete_message(message)




async def restart_notification():
    if await aiopath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
    else:
        chat_id, msg_id = 0, 0

    async def send_incompelete_task_message(cid, msg):
        try:
            if msg.startswith('Restarted Successfully!'):
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text='Restarted Successfully!')
                await bot.send_message(chat_id, msg, disable_web_page_preview=True, reply_to_message_id=msg_id)
                await aioremove(".restartmsg")
            else:
                await bot.send_message(chat_id=cid, text=msg, disable_web_page_preview=True,
                                       disable_notification=True)
        except Exception as e:
            LOGGER.error(e)
    if DATABASE_URL:
        if INCOMPLETE_TASK_NOTIFIER and (notifier_dict := await DbManger().get_incomplete_tasks()):
            for cid, data in notifier_dict.items():
                msg = 'Restarted Successfully!' if cid == chat_id else 'Bot Restarted!'
                for tag, links in data.items():
                    msg += f"\n\n👤 {tag} Do your tasks again. \n"
                    for index, link in enumerate(links, start=1):
                        msg += f" {index}: {link} \n"
                        if len(msg.encode()) > 4000:
                            await send_incompelete_task_message(cid, msg)
                            msg = ''
                if msg:
                    await send_incompelete_task_message(cid, msg)

        if STOP_DUPLICATE_TASKS:
            await DbManger().clear_download_links()


    if await aiopath.isfile(".restartmsg"):
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text='Restarted Successfully!')
        except:
            pass
        await aioremove(".restartmsg")


async def main():
    await gather(start_cleanup(), torrent_search.initiate_search_tools(), restart_notification(), set_commands(bot))
    await sync_to_async(start_aria2_listener, wait=False)

    bot.add_handler(MessageHandler(start,   filters=command(BotCommands.StartCommand)))
    bot.add_handler(MessageHandler(log,     filters=command(BotCommands.LogCommand)     & CustomFilters.sudo))
    bot.add_handler(MessageHandler(restart, filters=command(BotCommands.RestartCommand) & CustomFilters.sudo))
    bot.add_handler(MessageHandler(ping,    filters=command(BotCommands.PingCommand)    & CustomFilters.authorized))
    bot.add_handler(MessageHandler(bot_help,filters=command(BotCommands.HelpCommand)    & CustomFilters.authorized))
    bot.add_handler(MessageHandler(stats,   filters=command(BotCommands.StatsCommand)   & CustomFilters.authorized))
    bot.add_handler(MessageHandler(stats,   filters=command(BotCommands.StatsCommand)   & CustomFilters.authorized))
    bot.add_handler(CallbackQueryHandler(send_close_signal, filters=regex("^close_signal")))
    bot.add_handler(CallbackQueryHandler(send_bot_stats,    filters=regex("^show_bot_stats")))
    bot.add_handler(CallbackQueryHandler(send_sys_stats,    filters=regex("^show_sys_stats")))
    bot.add_handler(CallbackQueryHandler(send_repo_stats,   filters=regex("^show_repo_stats")))
    bot.add_handler(CallbackQueryHandler(send_bot_limits,   filters=regex("^show_bot_limits")))
    LOGGER.info("Congratulations, Bot Started Successfully!")
    signal(SIGINT, exit_clean_up)

bot.loop.run_until_complete(main())
bot.loop.run_forever()

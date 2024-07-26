import datetime
import io
import random
from string import ascii_letters as letters

import pytz
from telegram import ChatMember, ChatMemberUpdated
from telegram.ext import ContextTypes


async def _delete_message_cb(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    msg_id = job.data
    try:
        await context.bot.delete_message(job.chat_id, msg_id)
    except Exception as e:
        pass


async def delete_message_later(delay: float, chat_id, msg_id: int,  context: ContextTypes.DEFAULT_TYPE):
    name=f"deljob_{chat_id}_{msg_id}"
    context.job_queue.run_once(_delete_message_cb, delay, chat_id=chat_id, name=name, data=msg_id)
    return name

async def _ban_user_cb(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id, time = job.data.split('-')
    user_id = int(user_id)
    time = int(time)
    ban_time = datetime.datetime.now(pytz.utc) + datetime.timedelta(minutes=time)
    print(ban_time)
    await context.bot.ban_chat_member(job.chat_id, user_id, ban_time)


async def ban_user_later(delay: float, chat_id, user_id: int, time, context: ContextTypes.DEFAULT_TYPE):
    name=f"banjob_{chat_id}_{user_id}"
    context.job_queue.run_once(_ban_user_cb, delay, chat_id=chat_id, name=name , data=f"{user_id}-{time}")
    return name

def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


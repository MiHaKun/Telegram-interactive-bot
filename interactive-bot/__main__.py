import os
import random
import time
from datetime import datetime, timedelta
from string import ascii_letters as letters
import asyncio # Already present, but needed for broadcast delay
from telegram.constants import ChatType, UpdateType

import httpx
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)
from telegram.helpers import mention_html

from db.database import SessionMaker, engine
from db.model import Base, FormnStatus, MediaGroupMesssage, MessageMap, User

from . import (
    admin_group_id,
    admin_user_ids,
    app_name,
    bot_token,
    is_delete_topic_as_ban_forever,
    is_delete_user_messages,
    logger,
    welcome_message,
    disable_captcha,
    message_interval,
)
from .utils import delete_message_later

# 创建表（使用的sqlite，是无法轻易alter表的。如果改动，需要删除重建。无法merge）
Base.metadata.create_all(bind=engine)
db = SessionMaker()


# 延时发送媒体组消息的回调
async def _send_media_group_later(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    media_group_id = job.data
    _, from_chat_id, target_id, dir = job.name.split("_")

    # 数据库内查找对应的媒体组消息。
    media_group_msgs = (
        db.query(MediaGroupMesssage)
        .filter(
            MediaGroupMesssage.media_group_id == media_group_id,
            MediaGroupMesssage.chat_id == from_chat_id,
        )
        .all()
    )
    chat = await context.bot.get_chat(target_id)
    if dir == "u2a":
        # 发送给群组
        u = db.query(User).filter(User.user_id == from_chat_id).first()
        message_thread_id = u.message_thread_id
        sents = await chat.send_copies(
            from_chat_id,
            [m.message_id for m in media_group_msgs],
            message_thread_id=message_thread_id,
        )
        for sent, msg in zip(sents, media_group_msgs):
            msg_map = MessageMap(
                user_chat_message_id=msg.message_id,
                group_chat_message_id=sent.message_id,
                user_id=u.user_id,
            )
            db.add(msg_map)
            db.commit()
    else:
        # 发送给用户
        sents = await chat.send_copies(
            from_chat_id, [m.message_id for m in media_group_msgs]
        )
        for sent, msg in zip(sents, media_group_msgs):
            msg_map = MessageMap(
                user_chat_message_id=sent.message_id,
                group_chat_message_id=msg.message_id,
                user_id=target_id,
            )
            db.add(msg_map)
            db.commit()


# 延时发送媒体组消息
async def send_media_group_later(
    delay: float,
    chat_id,
    target_id,
    media_group_id: int,
    dir,
    context: ContextTypes.DEFAULT_TYPE,
):
    name = f"sendmediagroup_{chat_id}_{target_id}_{dir}"
    context.job_queue.run_once(
        _send_media_group_later, delay, chat_id=chat_id, name=name, data=media_group_id
    )
    return name


def update_user_db(user: telegram.User):
    if db.query(User).filter(User.user_id == user.id).first():
        return
    u = User(
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
    )
    db.add(u)
    db.commit()

async def send_contact_card(
    chat_id, message_thread_id, user: User, update: Update, context: ContextTypes
):
    buttons = []
    try: # Minimal check for premium status
        tg_user = await context.bot.get_chat(user.user_id)
        is_premium = tg_user.is_premium or False
    except Exception:
        is_premium = False

    buttons.append(
        [
            InlineKeyboardButton(
                f"{'🏆 高级会员' if is_premium else '✈️ 普通会员' }",
                url=f"https://github.com/MiHaKun/Telegram-interactive-bot",
            )
        ]
    )
    if user.username:
        buttons.append(
            [InlineKeyboardButton("👤 直接联络", url=f"https://t.me/{user.username}")]
        )

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    user_photo = await context.bot.get_user_profile_photos(user.id)

    if user_photo.total_count:
        pic = user_photo.photos[0][-1].file_id
        await context.bot.send_photo(
            chat_id,
            photo=pic,
            caption=f"👤 {mention_html(user.id, user.first_name or str(user.id))}\n\n📱 {user.id}\n\n🔗 @{user.username if user.username else '无'}",
            message_thread_id=message_thread_id,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    else:
        await context.bot.send_contact(
            chat_id,
            phone_number="11111",
            first_name=user.first_name or "用户",
            last_name=user.last_name,
            message_thread_id=message_thread_id,
            reply_markup=reply_markup,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_user_db(user)
    # check whether is admin
    if user.id in admin_user_ids:
        logger.info(f"{user.first_name}({user.id}) is admin")
        try:
            bg = await context.bot.get_chat(admin_group_id)
            if bg.type == "supergroup" or bg.type == "group":
                logger.info(f"admin group is {bg.title}")
        except Exception as e:
            logger.error(f"admin group error {e}")
            await update.message.reply_html(
                f"⚠️⚠️后台管理群组设置错误，请检查配置。⚠️⚠️\n你需要确保已经将机器人 @{context.bot.username} 邀请入管理群组并且给与了管理员权限。\n错误细节：{e}\n"
            )
            return # Keep original return
        await update.message.reply_html(
            f"你好管理员 {mention_html(user.id, user.full_name)} ({user.id})\n\n欢迎使用 {app_name} 机器人。\n\n 目前你的配置完全正确。可以在群组 <b> {bg.title} </b> 中使用机器人。"
        )
    else:
        await update.message.reply_html(
            f"{mention_html(user.id, user.full_name)} 同学：\n\n{welcome_message}"
        )


async def check_human(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if context.user_data.get("is_human", False) == False:
        if context.user_data.get("is_human_error_time", 0) > time.time() - 120:
            # 2分钟内禁言
            await update.message.reply_html("你已经被禁言,请稍后再尝试。")
            return False
        img_dir = "./assets/imgs"
        try:
            if not os.path.isdir(img_dir) or not os.listdir(img_dir):
                 logger.warning(f"Captcha image directory '{img_dir}' not found or empty. Skipping check.")
                 context.user_data["is_human"] = True
                 return True

            file_name = random.choice(os.listdir(img_dir))
            code = file_name.replace("image_", "").replace(".png", "")
            file_path = os.path.join(img_dir, file_name)

            codes = ["".join(random.sample(letters, 5)) for _ in range(0, 7)]
            codes.append(code)
            random.shuffle(codes)

            photo_file_id = context.bot_data.get(f"image|{code}")
            photo_to_send = photo_file_id if photo_file_id else file_path

            buttons = [
                InlineKeyboardButton(x, callback_data=f"vcode_{x}_{user.id}") for x in codes
            ]
            button_matrix = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]

            captcha_text = f"{mention_html(user.id, user.first_name or str(user.id))}请选择图片中的文字。回答错误将无法联系客服。"

            if photo_file_id:
                sent = await update.message.reply_photo(
                    photo=photo_file_id,
                    caption=captcha_text,
                    reply_markup=InlineKeyboardMarkup(button_matrix),
                    parse_mode="HTML",
                )
            else:
                 with open(file_path, "rb") as f:
                     sent = await update.message.reply_photo(
                        photo=f,
                        caption=captcha_text,
                        reply_markup=InlineKeyboardMarkup(button_matrix),
                        parse_mode="HTML",
                     )
                 if sent.photo:
                     biggest_photo = sorted(sent.photo, key=lambda x: x.file_size, reverse=True)[0]
                     context.bot_data[f"image|{code}"] = biggest_photo.file_id

            context.user_data["vcode"] = code
            context.user_data["vcode_message_id"] = sent.message_id
            await delete_message_later(60, sent.chat.id, sent.message_id, context)
            return False
        except Exception as e:
             logger.error(f"Error during captcha generation: {e}")
             await update.message.reply_html("无法加载验证码，请稍后重试。")
             context.user_data["is_human"] = True
             return True
    return True


async def callback_query_vcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    try:
        _, code_clicked, target_user_id_str = query.data.split("_", 2)
    except ValueError:
        logger.warning(f"Invalid vcode callback data: {query.data}")
        return

    if target_user_id_str == str(user.id):
        correct_code = context.user_data.get("vcode")
        if code_clicked == correct_code:
            await query.answer("正确，欢迎。")
            await context.bot.send_message(
                update.effective_chat.id,
                f"{mention_html(user.id, user.first_name or str(user.id))} , 欢迎。",
                parse_mode="HTML",
            )
            context.user_data["is_human"] = True
            context.user_data.pop("vcode", None)
            context.user_data.pop("vcode_message_id", None)
            context.user_data.pop("is_human_error_time", None)
        else:
            await query.answer("~错误~，禁言2分钟")
            context.user_data["is_human_error_time"] = time.time()
            context.user_data.pop("vcode", None)
            context.user_data.pop("vcode_message_id", None)
    try:
        await query.message.delete()
    except:
        pass


async def forwarding_message_u2a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not disable_captcha:
        if not await check_human(update, context):
            return
    if message_interval:
        if context.user_data.get("last_message_time", 0) > time.time() - message_interval:
            await update.message.reply_html("请不要频繁发送消息。")
            return
        context.user_data["last_message_time"] = time.time()
    user = update.effective_user
    update_user_db(user)
    chat_id = admin_group_id
    # attachment = update.message.effective_attachment # Unused
    message = update.message

    u = db.query(User).filter(User.user_id == user.id).first()
    if not u: return

    message_thread_id = u.message_thread_id
    if message_thread_id:
        f = db.query(FormnStatus).filter(FormnStatus.message_thread_id == message_thread_id).first()
        if f and f.status == "closed":
            await update.message.reply_html(
                "客服已经关闭对话。如需联系，请利用其他途径联络客服回复和你的对话。"
            )
            return
    if not message_thread_id:
        try:
            formn = await context.bot.create_forum_topic(
                chat_id,
                name=f"{user.full_name}|{user.id}", # Naming from user's version
            )
            message_thread_id = formn.message_thread_id
            u.message_thread_id = message_thread_id
            db.add(FormnStatus(message_thread_id=message_thread_id, status="opened"))
            db.add(u)
            db.commit()

            await context.bot.send_message(
                chat_id,
                f"新的用户 {mention_html(user.id, user.full_name)} 开始了一个新的会话。",
                message_thread_id=message_thread_id,
                parse_mode="HTML",
            )
            await send_contact_card(chat_id, message_thread_id, u, update, context)
        except Exception as e:
             logger.error(f"Failed topic creation for {user.id}: {e}")
             await message.reply_html("创建会话时出错，请重试。")
             return

    params = {"message_thread_id": message_thread_id}
    if message.reply_to_message:
        reply_in_user_chat = message.reply_to_message.message_id
        msg_map = db.query(MessageMap).filter(MessageMap.user_chat_message_id == reply_in_user_chat).first()
        if msg_map:
            params["reply_to_message_id"] = msg_map.group_chat_message_id
    try:
        if message.media_group_id:
            is_first = not db.query(MediaGroupMesssage).filter_by(media_group_id=message.media_group_id, chat_id=message.chat.id).first()
            msg = MediaGroupMesssage(
                chat_id=message.chat.id,
                message_id=message.message_id,
                media_group_id=message.media_group_id,
                is_header=is_first,
                caption_html=message.caption_html if is_first else None
            )
            db.add(msg)
            db.commit()
            if message.media_group_id != context.user_data.get("current_media_group_id", 0):
                context.user_data["current_media_group_id"] = message.media_group_id
                await send_media_group_later(
                    5, user.id, chat_id, message.media_group_id, "u2a", context
                )
            return
        else:
            target_chat = await context.bot.get_chat(chat_id)
            sent_msg = await target_chat.send_copy(
                from_chat_id=message.chat.id,
                message_id=message.id,
                **params
            )
            msg_map = MessageMap(
                user_chat_message_id=message.id,
                group_chat_message_id=sent_msg.message_id,
                user_id=user.id,
            )
            db.add(msg_map)
            db.commit()

    except BadRequest as e:
        if is_delete_topic_as_ban_forever:
            await update.message.reply_html(
                f"发送失败，你的对话已经被客服删除。请联系客服重新打开对话。"
            )
        else:
            u.message_thread_id = 0
            db.add(u)
            db.query(FormnStatus).filter(FormnStatus.message_thread_id == message_thread_id).delete()
            db.commit()
            await update.message.reply_html(
                f"发送失败，你的对话已经被客服删除。请再发送一条消息用来激活对话。"
            )
    except Exception as e:
        await update.message.reply_html(
            f"发送失败: {e}\n"
        )


async def forwarding_message_a2u(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or message.chat.id != admin_group_id: return
    # update_user_db(update.effective_user)

    message_thread_id = message.message_thread_id
    if not message_thread_id: return
    if message.from_user.is_bot: return

    user_id = 0
    u = db.query(User).filter(User.message_thread_id == message_thread_id).first()
    if u: user_id = u.user_id
    if not user_id:
        logger.debug(f"No user for message {message.id} in topic {message_thread_id}")
        return

    if message.forum_topic_created:
        f = FormnStatus(message_thread_id=message.message_thread_id, status="opened")
        db.add(f)
        db.commit()
        return
    if message.forum_topic_closed:
        await context.bot.send_message(
            user_id, "对话已经结束。对方已经关闭了对话。你的留言将被忽略。"
        )
        f = db.query(FormnStatus).filter(FormnStatus.message_thread_id == message.message_thread_id).first()
        if f:
            f.status = "closed"
            db.add(f)
            db.commit()
        return
    if message.forum_topic_reopened:
        await context.bot.send_message(user_id, "对方重新打开了对话。可以继续对话了。")
        f = db.query(FormnStatus).filter(FormnStatus.message_thread_id == message.message_thread_id).first()
        if f:
            f.status = "opened"
            db.add(f)
            db.commit()
        return

    f = db.query(FormnStatus).filter(FormnStatus.message_thread_id == message_thread_id).first()
    if f and f.status == "closed":
        await update.message.reply_html(
            "对话已经结束。希望和对方联系，需要打开对话。"
        )
        return

    target_chat_id = user_id
    params = {}
    if message.reply_to_message:
        reply_in_admin = message.reply_to_message.message_id
        msg_map = db.query(MessageMap).filter(MessageMap.group_chat_message_id == reply_in_admin).first()
        if msg_map:
            params["reply_to_message_id"] = msg_map.user_chat_message_id
    try:
        if message.media_group_id:
            is_first = not db.query(MediaGroupMesssage).filter_by(media_group_id=message.media_group_id, chat_id=message.chat.id).first()
            msg = MediaGroupMesssage(
                chat_id=message.chat.id,
                message_id=message.message_id,
                media_group_id=message.media_group_id,
                is_header=is_first,
                caption_html=message.caption_html if is_first else None,
            )
            db.add(msg)
            db.commit()
            if is_first:
                await send_media_group_later(
                    5,
                    message.chat.id,
                    user_id,
                    message.media_group_id,
                    "a2u",
                    context,
                )
            return
        else:
            chat = await context.bot.get_chat(target_chat_id)
            sent_msg = await chat.send_copy(
                from_chat_id=message.chat.id,
                message_id=message.id,
                **params
            )
            msg_map = MessageMap(
                group_chat_message_id=message.id,
                user_chat_message_id=sent_msg.message_id,
                user_id=user_id,
            )
            db.add(msg_map)
            db.commit()

    except Exception as e:
        await update.message.reply_html(
            f"发送失败: {e}\n"
        )

async def handle_edited_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles edited messages from the user's private chat."""
    if not update.edited_message: return
    edited_msg = update.edited_message
    edited_msg_id = edited_msg.message_id

    msg_map = db.query(MessageMap).filter(MessageMap.user_chat_message_id == edited_msg_id).first()
    if not msg_map or not msg_map.group_chat_message_id: return

    group_msg_id = msg_map.group_chat_message_id

    try:
        if edited_msg.text is not None:
            await context.bot.edit_message_text(
                chat_id=admin_group_id, message_id=group_msg_id,
                text=edited_msg.text_html, parse_mode='HTML')
        elif edited_msg.caption is not None:
            await context.bot.edit_message_caption(
                chat_id=admin_group_id, message_id=group_msg_id,
                caption=edited_msg.caption_html, parse_mode='HTML')
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Failed sync user edit {edited_msg_id} -> {group_msg_id}: {e}")
    except Exception as e:
        logger.error(f"Error syncing user edit {edited_msg_id} -> {group_msg_id}: {e}")

async def handle_edited_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles edited messages from the admin group topic."""
    if not update.edited_message: return
    if update.edited_message.chat.id != admin_group_id: return

    edited_msg = update.edited_message
    edited_msg_id = edited_msg.message_id
    message_thread_id = edited_msg.message_thread_id

    if not message_thread_id or edited_msg.from_user.is_bot: return

    msg_map = db.query(MessageMap).filter(MessageMap.group_chat_message_id == edited_msg_id).first()
    if not msg_map or not msg_map.user_chat_message_id: return

    user_chat_msg_id = msg_map.user_chat_message_id
    user_id = msg_map.user_id

    try:
        if edited_msg.text is not None:
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=user_chat_msg_id,
                text=edited_msg.text_html, parse_mode='HTML')
        elif edited_msg.caption is not None:
            await context.bot.edit_message_caption(
                chat_id=user_id, message_id=user_chat_msg_id,
                caption=edited_msg.caption_html, parse_mode='HTML')
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Failed sync admin edit {edited_msg_id} -> {user_chat_msg_id}: {e}")
    except Exception as e:
        logger.error(f"Error syncing admin edit {edited_msg_id} -> {user_chat_msg_id}: {e}")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    if not user.id in admin_user_ids:
        await message.reply_html("你没有权限执行此操作。")
        return

    message_thread_id = message.message_thread_id
    if not message_thread_id:
        await message.reply_html("请在话题内使用 /clear。")
        return

    try:
        await context.bot.delete_forum_topic(
            message.chat.id, message_thread_id
        )
        target_user_for_clear = db.query(User).filter(User.message_thread_id == message_thread_id).first()
        db.query(FormnStatus).filter(FormnStatus.message_thread_id == message_thread_id).delete()
        if target_user_for_clear:
            target_user_for_clear.message_thread_id = None
            db.add(target_user_for_clear)
        db.commit()

    except Exception as e:
        logger.error(f"Error deleting topic {message_thread_id} in clear: {e}")

    if is_delete_user_messages:
        target_user = db.query(User).filter(User.message_thread_id == message_thread_id).first() # Might be None now
        if not target_user:
             # Try finding user based on who the topic *was* for if possible? No easy way in original structure.
             logger.warning(f"Cannot find user for cleared topic {message_thread_id} to delete messages.")


        if target_user:
            all_messages_in_user_chat = (
                db.query(MessageMap).filter(MessageMap.user_id == target_user.user_id).all()
            )
            ids_to_delete = [msg.user_chat_message_id for msg in all_messages_in_user_chat if msg.user_chat_message_id]
            if ids_to_delete:
                try:
                    await context.bot.delete_messages(
                        target_user.user_id,
                        ids_to_delete[:100], 
                    )
                except Exception as e:
                    logger.error(f"Error deleting messages for user {target_user.user_id}: {e}")


async def _broadcast(context: ContextTypes.DEFAULT_TYPE):
    users = db.query(User).all()
    try:
        job_data = context.job.data
        msg_id_str, chat_id_str = job_data.split("_", 1)
        msg_id = int(msg_id_str)
        chat_id = int(chat_id_str)
    except:
        logger.error(f"Invalid job data for broadcast: {job_data}")
        return

    success = 0
    failed = 0
    blocked = 0
    send_delay = 0.1

    for u in users:
        try:
            chat = await context.bot.get_chat(u.user_id)
            await chat.send_copy(chat_id, msg_id)
            success += 1
        except BadRequest as e:
             if "blocked" in str(e).lower() or "deactivated" in str(e).lower(): blocked += 1
             else: failed += 1; logger.warning(f"Broadcast BadRequest for {u.user_id}: {e}")
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast Exception for {u.user_id}: {e}")
        await asyncio.sleep(send_delay)

    logger.info(f"Broadcast result - Success: {success}, Failed: {failed}, Blocked: {blocked}")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user.id in admin_user_ids:
        await update.message.reply_html("你没有权限执行此操作。")
        return

    if not update.message.reply_to_message:
        await update.message.reply_html(
            "这条指令需要回复一条消息，被回复的消息将被广播。"
        )
        return

    job_data = f"{update.message.reply_to_message.id}_{update.effective_chat.id}"
    job_name = f"broadcast_{update.message.reply_to_message.id}"

    context.job_queue.run_once(
        _broadcast,
        0,
        data=job_data,
        name=job_name
    )
    await update.message.reply_html("广播任务已添加。")


async def error_in_send_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning("error_in_send_media_group called (likely unused)")
    if update and update.message:
        await update.message.reply_html(
            "错误的消息类型。退出发送媒体组。后续对话将直接转发。"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Exception while handling an update: {context.error} ", exc_info=context.error)


if __name__ == "__main__":
    pickle_persistence = PicklePersistence(filepath=f"./assets/{app_name}.pickle")
    application = (
        ApplicationBuilder()
        .token(bot_token)
        .persistence(persistence=pickle_persistence)
        .build()
    )

    application.add_handler(CommandHandler("start", start, filters.ChatType.PRIVATE))

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE,
            forwarding_message_u2a
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Chat(admin_group_id) & filters.IS_TOPIC_MESSAGE & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE,
            forwarding_message_a2u
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.UpdateType.EDITED_MESSAGE,
            handle_edited_user_message
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Chat(admin_group_id) & filters.IS_TOPIC_MESSAGE & filters.UpdateType.EDITED_MESSAGE,
            handle_edited_admin_message
        )
    )

    application.add_handler(CommandHandler("clear", clear, filters.Chat(admin_group_id)))
    application.add_handler(CommandHandler("broadcast", broadcast, filters.Chat(admin_group_id)))
    application.add_handler(
        CallbackQueryHandler(callback_query_vcode, pattern="^vcode_")
    )
    application.add_error_handler(error_handler)

    application.run_polling()

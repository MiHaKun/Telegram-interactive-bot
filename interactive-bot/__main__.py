import os
import random
import time
from datetime import datetime, timedelta
from string import ascii_letters as letters

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
    buttons.append(
        [
            InlineKeyboardButton(
                f"{'🏆 高级会员' if user.is_premium else '✈️ 普通会员' }",
                url=f"https://github.com/MiHaKun/Telegram-interactive-bot",
            )
        ]
    )
    if user.username:
        buttons.append(
            [InlineKeyboardButton("👤 直接联络", url=f"https://t.me/{user.username}")]
        )

    user_photo = await context.bot.get_user_profile_photos(user.id)

    if user_photo.total_count:
        pic = user_photo.photos[0][-1].file_id
        await context.bot.send_photo(
            chat_id,
            photo=pic,
            caption=f"👤 {mention_html(user.id, user.first_name)}\n\n📱 {user.id}\n\n🔗 @{user.username if user.username else '无'}",
            message_thread_id=message_thread_id,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    else:
        await context.bot.send_contact(
            chat_id,
            phone_number="11111",
            first_name=user.first_name,
            last_name=user.last_name,
            message_thread_id=message_thread_id,
            reply_markup=InlineKeyboardMarkup(buttons),
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
                f"⚠️⚠️后台管理群组设置错误，请检查配置。⚠️⚠️\n你需要确保已经将机器人 @{context.bot.username} 邀请入管理群组并且给与了管理员权限。\n错误细节：{e}\n请联系 @MrMiHa 获取技术支持。"
            )
            return ConversationHandler.END
        await update.message.reply_html(
            f"你好管理员 {user.first_name}({user.id})\n\n欢迎使用 {app_name} 机器人。\n\n 目前你的配置完全正确。可以在群组 <b> {bg.title} </b> 中使用机器人。"
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
        file_name = random.choice(os.listdir("./assets/imgs"))
        code = file_name.replace("image_", "").replace(".png", "")
        file = f"./assets/imgs/{file_name}"
        codes = ["".join(random.sample(letters, 5)) for _ in range(0, 7)]
        codes.append(code)
        random.shuffle(codes)

        photo = context.bot_data.get(f"image|{code}")
        if not photo:
            # 没发送过，就用内置图片。
            photo = file
        buttons = [
            InlineKeyboardButton(x, callback_data=f"vcode_{x}_{user.id}") for x in codes
        ]
        button_matrix = [buttons[i : i + 4] for i in range(0, len(buttons), 4)]
        sent = await update.message.reply_photo(
            photo,
            f"{mention_html(user.id, user.first_name)}请选择图片中的文字。回答错误将无法联系客服。",
            reply_markup=InlineKeyboardMarkup(button_matrix),
            parse_mode="HTML",
        )
        # 存下已经发送过的图片
        biggest_photo = sorted(sent.photo, key=lambda x: x.file_size, reverse=True)[0]
        context.bot_data[f"image|{code}"] = biggest_photo.file_id
        context.user_data["vcode"] = code
        await delete_message_later(60, sent.chat.id, sent.message_id, context)
        return False
    return True


async def callback_query_vcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    code = query.data.split("_")[1]
    user_id = query.data.split("_")[2]
    if user_id == str(user.id):
        # 是正确的人点击
        if code == context.user_data.get("vcode"):
            # 点击合法
            await query.answer(f"正确，欢迎。")
            sent = await context.bot.send_message(
                update.effective_chat.id,
                f"{mention_html(user.id, user.first_name)} , 欢迎。",
                parse_mode="HTML",
            )
            context.user_data["is_human"] = True
        else:
            await query.answer(f"~错误~，禁言2分钟")
            context.user_data["is_human_error_time"] = time.time()
    await query.message.delete()


async def forwarding_message_u2a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not disable_captcha:
        if not await check_human(update, context):
            return
    user = update.effective_user
    update_user_db(user)
    chat_id = admin_group_id
    attachment = update.message.effective_attachment
    # await update.message.forward(chat_id)
    u = db.query(User).filter(User.user_id == user.id).first()
    message_thread_id = u.message_thread_id
    if (
        f := db.query(FormnStatus)
        .filter(FormnStatus.message_thread_id == message_thread_id)
        .first()
    ):
        if f.status == "closed":
            await update.message.reply_html(
                "客服已经关闭对话。如需联系，请利用其他途径联络客服回复和你的对话。"
            )
            return
    if not message_thread_id:
        formn = await context.bot.create_forum_topic(
            chat_id,
            name=f"工单{random.randint(10000,99999)}|{user.full_name}|{user.id}",
        )
        message_thread_id = formn.message_thread_id
        u.message_thread_id = message_thread_id
        await context.bot.send_message(
            chat_id,
            f"新的用户 {mention_html(user.id, user.full_name)} 开始了一个新的会话。",
            message_thread_id=message_thread_id,
            parse_mode="HTML",
        )
        await send_contact_card(chat_id, message_thread_id, user, update, context)
        db.add(u)
        db.commit()

    # 构筑下发送参数
    params = {"message_thread_id": message_thread_id}
    if update.message.reply_to_message:
        # 用户引用了一条消息。我们需要找到这条消息在群组中的id
        reply_in_user_chat = update.message.reply_to_message.message_id
        if (
            msg_map := db.query(MessageMap)
            .filter(MessageMap.user_chat_message_id == reply_in_user_chat)
            .first()
        ):
            params["reply_to_message_id"] = msg_map.group_chat_message_id
    try:
        if update.message.media_group_id:
            msg = MediaGroupMesssage(
                chat_id=update.message.chat.id,
                message_id=update.message.message_id,
                media_group_id=update.message.media_group_id,
                is_header=False,
                caption_html=update.message.caption_html,
            )
            db.add(msg)
            db.commit()
            if update.message.media_group_id != context.user_data.get(
                "current_media_group_id", 0
            ):
                context.user_data["current_media_group_id"] = (
                    update.message.media_group_id
                )
                await send_media_group_later(
                    5, user.id, chat_id, update.message.media_group_id, "u2a", context
                )
            return
        else:
            chat = await context.bot.get_chat(chat_id)
            sent_msg = await chat.send_copy(
                update.effective_chat.id, update.message.id, **params
            )

        msg_map = MessageMap(
            user_chat_message_id=update.message.id,
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
            db.commit()
            await update.message.reply_html(
                f"发送失败，你的对话已经被客服删除。请再发送一条消息用来激活对话。"
            )
    except Exception as e:
        await update.message.reply_html(
            f"发送失败: {e}\n请联系 @MrMiHa 汇报这个错误。谢谢"
        )


async def forwarding_message_a2u(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_db(update.effective_user)
    message_thread_id = update.message.message_thread_id
    if not message_thread_id:
        # general message, ignore
        return
    user_id = 0
    if u := db.query(User).filter(User.message_thread_id == message_thread_id).first():
        user_id = u.user_id
    if not user_id:
        logger.debug(update.message)
        return
    if update.message.forum_topic_created:
        f = FormnStatus(
            message_thread_id=update.message.message_thread_id, status="opened"
        )
        db.add(f)
        db.commit()
        return
    if update.message.forum_topic_closed:
        await context.bot.send_message(
            user_id, "对话已经结束。对方已经关闭了对话。你的留言将被忽略。"
        )
        if (
            f := db.query(FormnStatus)
            .filter(FormnStatus.message_thread_id == update.message.message_thread_id)
            .first()
        ):
            f.status = "closed"
            db.add(f)
            db.commit()
        return
    if update.message.forum_topic_reopened:
        await context.bot.send_message(user_id, "对方重新打开了对话。可以继续对话了。")
        if (
            f := db.query(FormnStatus)
            .filter(FormnStatus.message_thread_id == update.message.message_thread_id)
            .first()
        ):
            f.status = "opened"
            db.add(f)
            db.commit()
        return
    if (
        f := db.query(FormnStatus)
        .filter(FormnStatus.message_thread_id == message_thread_id)
        .first()
    ):
        if f.status == "closed":
            await update.message.reply_html(
                "对话已经结束。希望和对方联系，需要打开对话。"
            )
            return
    chat_id = user_id
    # 构筑下发送参数
    params = {}
    if update.message.reply_to_message:
        # 群组中，客服回复了一条消息。我们需要找到这条消息在用户中的id
        reply_in_admin = update.message.reply_to_message.message_id
        if (
            msg_map := db.query(MessageMap)
            .filter(MessageMap.group_chat_message_id == reply_in_admin)
            .first()
        ):
            params["reply_to_message_id"] = msg_map.user_chat_message_id
    try:
        if update.message.media_group_id:
            msg = MediaGroupMesssage(
                chat_id=update.message.chat.id,
                message_id=update.message.message_id,
                media_group_id=update.message.media_group_id,
                is_header=False,
                caption_html=update.message.caption_html,
            )
            db.add(msg)
            db.commit()
            if update.message.media_group_id != context.application.user_data[
                user_id
            ].get("current_media_group_id", 0):
                context.application.user_data[user_id][
                    "current_media_group_id"
                ] = update.message.media_group_id
                await send_media_group_later(
                    5,
                    update.effective_chat.id,
                    user_id,
                    update.message.media_group_id,
                    "a2u",
                    context,
                )
            return
        else:
            chat = await context.bot.get_chat(chat_id)
            sent_msg = await chat.send_copy(
                update.effective_chat.id, update.message.id, **params
            )
        msg_map = MessageMap(
            group_chat_message_id=update.message.id,
            user_chat_message_id=sent_msg.message_id,
            user_id=user_id,
        )
        db.add(msg_map)
        db.commit()

    except Exception as e:
        await update.message.reply_html(
            f"发送失败: {e}\n请联系 @MrMiHa 汇报这个错误。谢谢"
        )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user.id in admin_user_ids:
        await update.message.reply_html("你没有权限执行此操作。")
        return
    await context.bot.delete_forum_topic(
        update.effective_chat.id, update.message.message_thread_id
    )
    if not is_delete_user_messages:
        return
    if (
        target_user := db.query(User)
        .filter(User.message_thread_id == update.message.message_thread_id)
        .first()
    ):
        all_messages_in_user_chat = (
            db.query(MessageMap).filter(MessageMap.user_id == target_user.user_id).all()
        )
        await context.bot.delete_messages(
            target_user.user_id,
            [msg.user_chat_message_id for msg in all_messages_in_user_chat],
        )


async def _broadcast(context: ContextTypes.DEFAULT_TYPE):
    users = db.query(User).all()
    msg_id, chat_id = context.job.data.split("_")
    success = 0
    failed = 0
    for u in users:
        try:
            chat = await context.bot.get_chat(u.user_id)
            await chat.send_copy(chat_id, msg_id)
            success += 1
        except Exception as e:
            failed += 1


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

    context.job_queue.run_once(
        _broadcast,
        0,
        data=f"{update.message.reply_to_message.id}_{update.effective_chat.id}",
    )


async def error_in_send_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "错误的消息类型。退出发送媒体组。后续对话将直接转发。"
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(f"Exception while handling an update: {context.error} ")
    logger.debug(f"Exception detail is :", exc_info=context.error)


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
            ~filters.COMMAND & filters.ChatType.PRIVATE, forwarding_message_u2a
        )
    )
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND & filters.Chat([admin_group_id]), forwarding_message_a2u
        )
    )
    application.add_handler(
        CommandHandler("clear", clear, filters.Chat([admin_group_id]))
    )
    application.add_handler(
        CommandHandler("broadcast", broadcast, filters.Chat([admin_group_id]))
    )
    application.add_handler(
        CallbackQueryHandler(callback_query_vcode, pattern="^vcode_")
    )
    application.add_error_handler(error_handler)
    application.run_polling()

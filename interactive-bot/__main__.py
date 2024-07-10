from . import logger, api_id, api_hash, bot_token, app_name, welcome_message, admin_group_id, admin_user_id
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaAudio, InputMediaDocument, InputMediaPhoto ,InputMediaVideo
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, PicklePersistence, ConversationHandler
from telegram.helpers import create_deep_linked_url,mention_html
import telegram 
from .utils import send_contact_card

STATE_WAIT_MEDIA_START = 0
STATE_WAIT_MEDIA_GROUP = 1

from db.database import SessionMaker, engine
from db.model import MediaGroupMesssage, MessageMap, User,FormnStatus, Base

# 创建表（使用的sqlite，是无法轻易alter表的。如果改动，需要删除重建。无法merge）
Base.metadata.create_all(bind=engine)

db = SessionMaker()

def update_user_db(user: telegram.User):
    if db.query(User).filter(User.user_id == user.id).first(): return 
    u = User(user_id=user.id, first_name=user.first_name, last_name=user.last_name, username=user.username)
    db.merge(u)
    db.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = User(user_id=user.id, first_name=user.first_name, last_name=user.last_name, username=user.username)
    db.merge(u)
    db.commit()
    # check whether is admin
    if user.id == admin_user_id:
        logger.info(f"{user.first_name}({user.id}) is admin")
        try:
            bg = await context.bot.get_chat(admin_group_id)
            if bg.type == 'supergroup' or bg.type == 'group':
                logger.info(f"admin group is {bg.title}")
        except Exception as e:
            logger.error(f"admin group error {e}")
            await update.message.reply_html(f"⚠️⚠️后台管理群组设置错误，请检查配置。⚠️⚠️\n你需要确保已经将机器人 @{context.bot.username} 邀请入管理群组并且给与了管理员权限。\n错误细节：{e}\n请联系 @MrMiHa 获取技术支持。")
            return ConversationHandler.END
        await update.message.reply_html(f"你好管理员 {user.first_name}({user.id})\n\n欢迎使用 {app_name} 机器人。\n\n 目前你的配置完全正确。可以在群组 <b> {bg.title} </b> 中使用机器人。")
    else:
        await update.message.reply_html(f"{mention_html(user.id, user.full_name)} 同学：\n\n{welcome_message}")



async def forwarding_message_u2a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_user_db(user)
    chat_id = admin_group_id
    attachment = update.message.effective_attachment 
    # await update.message.forward(chat_id)
    u = db.query(User).filter(User.user_id == user.id).first()
    message_thread_id = u.message_thread_id
    if f := db.query(FormnStatus).filter(FormnStatus.message_thread_id == message_thread_id).first():
        if f.status == 'closed':
            await update.message.reply_html("客服已经关闭对话。如需联系，请利用其他途径联络客服回复和你的对话。")
            return
    if not message_thread_id:
        formn = await context.bot.create_forum_topic(chat_id, name=f"{user.full_name}|{user.id}")
        message_thread_id = formn.message_thread_id
        u.message_thread_id = message_thread_id
        await context.bot.send_message(chat_id, f"新的用户 {mention_html(user.id, user.full_name)} 开始了一个新的会话。", message_thread_id=message_thread_id, parse_mode='HTML')
        await send_contact_card(chat_id, message_thread_id, user, update, context)
        db.add(u)
        db.commit()
  
    # 构筑下发送参数
    params = {
        "message_thread_id": message_thread_id
    }
    if update.message.reply_to_message:
        # 用户引用了一条消息。我们需要找到这条消息在群组中的id
        reply_in_user_chat = update.message.reply_to_message.message_id
        if msg_map := db.query(MessageMap).filter(MessageMap.user_chat_message_id == reply_in_user_chat).first():
            params['reply_to_message_id'] =  msg_map.group_chat_message_id
    try:
        bad_type = ''
        if update.message.media_group_id:
            bad_type = "不支持媒体组类型(最好单个发送)。\n如果确定需要，请点击-> /start_to_send_media_group "
        else:
            chat = await context.bot.get_chat(chat_id)
            sent_msg = await chat.send_copy(update.effective_chat.id, update.message.id, **params)

        if bad_type:
            await update.message.reply_html(f"{bad_type}。请更换重新发送。（支持常用的文字、图片、音频、视频、文件等类型）")
        else:
            msg_map = MessageMap(user_chat_message_id=update.message.id, group_chat_message_id=sent_msg.message_id)
            db.add(msg_map)
            db.commit()


    except Exception as e:
        await update.message.reply_html(f"发送失败: {e}\n请联系 @MrMiHa 汇报这个错误。谢谢")

async def forwarding_message_a2u(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_user_db(update.effective_user)
    message_thread_id = update.message.message_thread_id
    if not message_thread_id:
        # general message, ignore
        return 
    if u := db.query(User).filter(User.message_thread_id == message_thread_id).first():
        user_id = u.user_id
        if not user_id:
            logger.debug(update.message)
            return     
    if update.message.forum_topic_created:
        f = FormnStatus(message_thread_id=update.message.message_thread_id, status='opened')
        db.add(f)
        db.commit()
        return 
    if update.message.forum_topic_closed:
        await context.bot.send_message(user_id, "对话已经结束。对方已经关闭了对话。你的留言将被忽略。")
        if f := db.query(FormnStatus).filter(FormnStatus.message_thread_id == update.message.message_thread_id).first():
            f.status = 'closed'
            db.add(f)
            db.commit()
        return 
    if update.message.forum_topic_reopened:
        await context.bot.send_message(user_id, "对方重新打开了对话。可以继续对话了。")
        if f := db.query(FormnStatus).filter(FormnStatus.message_thread_id == update.message.message_thread_id).first():
            f.status = 'opened'
            db.add(f)
            db.commit()        
        return
    if f := db.query(FormnStatus).filter(FormnStatus.message_thread_id == message_thread_id).first():
        if f.status == 'closed':
            await update.message.reply_html("对话已经结束。希望和对方联系，需要打开对话。")
            return
    chat_id = user_id
    # 构筑下发送参数
    params = {}
    if update.message.reply_to_message:
        # 群组中，客服回复了一条消息。我们需要找到这条消息在用户中的id
        reply_in_admin = update.message.reply_to_message.message_id
        if msg_map := db.query(MessageMap).filter(MessageMap.group_chat_message_id == reply_in_admin).first():
            params['reply_to_message_id'] =  msg_map.user_chat_message_id
    try:
        bad_type = ''
        if update.message.media_group_id:
            bad_type = "不支持媒体组类型(最好单个发送)。\n如果确定需要，请点击-> /start_to_send_media_group "
        else:
            chat = await context.bot.get_chat(chat_id)
            sent_msg = await chat.send_copy(update.effective_chat.id, update.message.id, **params)    
        if bad_type:
            await update.message.reply_html(f"{bad_type}。请更换重新发送。（支持常用的文字、图片、音频、视频、文件等类型）")
        else:
            msg_map = MessageMap(group_chat_message_id=update.message.id, user_chat_message_id=sent_msg.message_id)
            db.add(msg_map)
            db.commit()

    except Exception as e:
        await update.message.reply_html(f"发送失败: {e}\n请联系 @MrMiHa 汇报这个错误。谢谢")

async def start_to_send_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html("请开始发送,确认上传完毕后，请点击 /done")
    return STATE_WAIT_MEDIA_START

async def wait_media_start_idx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.media_group_id:
        context.user_data['current_media_group'] = []
        await update.message.reply_html("请发送一个媒体组，例如：一组图片、视频、音频等。/n点击 /start_to_send_media_group 重新开始。")
        return ConversationHandler.END
    attachment = update.message.effective_attachment
    context.user_data['current_media_group'] = [(attachment, update.message.caption_html)]
    return STATE_WAIT_MEDIA_GROUP

async def wait_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attachment = update.message.effective_attachment 
    logger.info(f"media-group_after {update.message.caption}")
    attachs = context.user_data['current_media_group']
    attachs.append((attachment, update.message.caption_html))
    context.user_data['current_media_group'] = attachs
    await update.message.reply_html("请观察媒体消息是否还在上传。如果完成，请点击 /done")
    return STATE_WAIT_MEDIA_GROUP

async def done_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    params = {}
    if chat.id == admin_group_id:
        message_thread_id = update.message.message_thread_id
        chat_id = context.bot_data.get(f"user_id|{message_thread_id}", 0)
    else:
        chat_id = admin_group_id
        params['message_thread_id'] = context.bot_data.get(f'mthread_id|{user.id}', 0)

    attachs = context.user_data['current_media_group']
    media_group = []
    for attach, caption in attachs:
        if isinstance(attach, telegram.Video):
            media_group.append(InputMediaVideo(attach.file_id, caption=caption))
        elif isinstance(attach, tuple ) and isinstance(attach[0], telegram.PhotoSize):
            media_group.append(InputMediaPhoto(attach[0].file_id, caption=caption))
            
    await context.bot.send_media_group(chat_id,media_group, **params)
    await update.message.reply_html(f"发送成功。")
    return ConversationHandler.END

async def error_in_send_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html("错误的消息类型。退出发送媒体组。后续对话将直接转发。")
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(f"Exception while handling an update: {context.error} ")
    logger.debug(f"Exception detail is :", exc_info=context.error)

if __name__ == '__main__':
    pickle_persistence = PicklePersistence(filepath=f"./assets/{app_name}.pickle")
    application = ApplicationBuilder().token(bot_token).persistence(persistence=pickle_persistence).build()

    application.add_handler(CommandHandler('start', start, filters.ChatType.PRIVATE))
    application.add_handler(ConversationHandler(
        entry_points=[CommandHandler('start_to_send_media_group', start_to_send_media_group, filters.COMMAND)],
        states={
            STATE_WAIT_MEDIA_START: [
                MessageHandler(~filters.COMMAND , wait_media_start_idx),
                CommandHandler("done", done_media_group, filters.COMMAND)
                ],
            STATE_WAIT_MEDIA_GROUP: [
                MessageHandler(~filters.COMMAND , wait_media_group),
                CommandHandler("done", done_media_group, filters.COMMAND)
            ]
        },
        fallbacks=[
            MessageHandler(filters.ALL, error_in_send_media_group),
            CommandHandler("done", done_media_group, filters.COMMAND)
        ]
    ))    
    application.add_handler(MessageHandler(~filters.COMMAND & filters.ChatType.PRIVATE, forwarding_message_u2a))
    application.add_handler(MessageHandler(~filters.COMMAND & filters.Chat([admin_group_id]), forwarding_message_a2u))


    application.add_error_handler(error_handler)
    application.run_polling()  

from . import logger, api_id, api_hash, bot_token, app_name, welcome_message, admin_group_id, admin_user_id
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaAudio, InputMediaDocument, InputMediaPhoto ,InputMediaVideo
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, PicklePersistence, ConversationHandler
from telegram.helpers import create_deep_linked_url,mention_html
import telegram 

STATE_SEND_MESSAGE = 1
STATE_MEDIA_GROUP = 2

async def send_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # todo: send media group
    pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
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
    chat_id = admin_group_id
    attachment = update.message.effective_attachment 
    # await update.message.forward(chat_id)
    message_thread_id = context.bot_data.get(f'mthread_id|{user.id}', 0)
    if not message_thread_id:
        formn = await context.bot.create_forum_topic(chat_id, name=f"{user.full_name}|{user.id}")
        message_thread_id = formn.message_thread_id
        context.bot_data[f'mthread_id|{user.id}'] = message_thread_id
        context.bot_data[f'user_id|{message_thread_id}'] = user.id
        await context.bot.send_message(chat_id, f"新的用户 {mention_html(user.id, user.full_name)} 开始了一个新的会话。", message_thread_id=message_thread_id, parse_mode='HTML')
    
    # 构筑下发送参数
    params = {
        "message_thread_id": message_thread_id
    }
    if update.message.reply_to_message:
        reply_in_user_chat = update.message.reply_to_message.message_id
        if msg_id_in_user_chat := context.bot_data.get(f'u2a|{user.id}|{reply_in_user_chat}', 0):
            params['reply_to_message_id'] =  msg_id_in_user_chat
    try:
        bad_type = ''
        if not attachment:
            sent_msg = await context.bot.send_message(chat_id, update.message.text_html, parse_mode='HTML', **params)
        elif update.message.media_group_id:
            bad_type = "不支持媒体组类型(最好单个发送)。\n如果确定需要，请点击-> /start_to_send_media_group "
        elif isinstance(attachment, telegram.Audio):
            sent_msg = await context.bot.send_audio(chat_id, attachment, caption=update.message.caption_html, parse_mode='HTML', **params)
        elif isinstance(attachment, telegram.Dice):
            sent_msg = await context.bot.send_dice(chat_id, attachment, **params)
        elif isinstance(attachment, telegram.Contact):
            sent_msg = await context.bot.send_contact(chat_id, contact=attachment, **params)
        elif isinstance(attachment, telegram.Document):
            sent_msg = await context.bot.send_document(chat_id, attachment, caption=update.message.caption_html, parse_mode='HTML', **params)
        elif isinstance(attachment, telegram.Animation):
            sent_msg = await context.bot.send_animation(chat_id, animation=attachment, **params)
        elif isinstance(attachment, telegram.Game):
            bad_type = '不支持游戏类型'
        elif isinstance(attachment, telegram.Invoice):
            bad_type = '不支持发票类型'
        elif isinstance(attachment, telegram.Location):
            sent_msg = await context.bot.send_location(chat_id, location=attachment, **params)
        elif isinstance(attachment, telegram.PassportData):
            bad_type = '不支持通行证类型'
        elif isinstance(attachment, tuple) and isinstance(attachment[0], telegram.PhotoSize):
            sent_msg = await context.bot.send_photo(chat_id, attachment[0].file_id, caption=update.message.caption_html, parse_mode='HTML', **params)
        elif isinstance(attachment, telegram.Poll):
            bad_type = '不支持投票类型'
        elif isinstance(attachment, telegram.Sticker):
            sent_msg = await context.bot.send_sticker(chat_id, attachment, **params)
        elif isinstance(attachment, telegram.Story):
            bad_type= '不支持故事类型'
        elif isinstance(attachment, telegram.SuccessfulPayment, **params):
            bad_type = '不支持支付类型'
        elif isinstance(attachment, telegram.Venue):
            sent_msg = await context.bot.send_venue(chat_id, venue=attachment,**params)
        elif isinstance(attachment, telegram.Video):
            sent_msg = await context.bot.send_video(chat_id, attachment,**params)
        elif isinstance(attachment, telegram.VideoNote):
            sent_msg = await context.bot.send_video_note(chat_id, attachment,**params)
        elif isinstance(attachment, telegram.Voice):
            sent_msg = await context.bot.send_voice(chat_id, attachment,**params)
        if bad_type:
            await update.message.reply_html(f"{bad_type}。请更换重新发送。（支持常用的文字、图片、音频、视频、文件等类型）")

        context.bot_data[f'a2u|{user.id}|{sent_msg.id}'] = update.message.id
        context.bot_data[f'u2a|{user.id}|{update.message.id}'] = sent_msg.message_id


    except Exception as e:
        await update.message.reply_html(f"发送失败: {e}")

async def forwarding_message_a2u(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_thread_id = update.message.message_thread_id
    user_id = context.bot_data.get(f"user_id|{message_thread_id}", 0)
    user_id = int(user_id)
    if not user_id:
        logger.debug(update.message)
        return 
    chat_id = user_id
    attachment = update.message.effective_attachment 
    # 构筑下发送参数
    params = {}
    if update.message.reply_to_message:
        reply_in_admin = update.message.reply_to_message.message_id
        if msg_id_in_admin := context.bot_data.get(f'a2u|{user_id}|{reply_in_admin}', 0):
            params['reply_to_message_id'] =  msg_id_in_admin
    try:
        bad_type = ''
        if not attachment:
            sent_msg = await context.bot.send_message(chat_id, update.message.text_html, parse_mode='HTML', **params)
        elif update.message.media_group_id:
            bad_type = "不支持媒体组类型(最好单个发送)。\n如果确定需要，请点击-> /start_to_send_media_group "
        elif isinstance(attachment, telegram.Audio):
            sent_msg = await context.bot.send_audio(chat_id, attachment, caption=update.message.caption_html, parse_mode='HTML', **params)
        elif isinstance(attachment, telegram.Dice):
            sent_msg = await context.bot.send_dice(chat_id, attachment, **params)
        elif isinstance(attachment, telegram.Contact):
            sent_msg = await context.bot.send_contact(chat_id, contact=attachment, **params)
        elif isinstance(attachment, telegram.Document):
            sent_msg = await context.bot.send_document(chat_id, attachment, caption=update.message.caption_html, parse_mode='HTML', **params)
        elif isinstance(attachment, telegram.Animation):
            sent_msg = await context.bot.send_animation(chat_id, animation=attachment, **params)
        elif isinstance(attachment, telegram.Game):
            bad_type = '不支持游戏类型'
        elif isinstance(attachment, telegram.Invoice):
            bad_type = '不支持发票类型'
        elif isinstance(attachment, telegram.Location):
            sent_msg = await context.bot.send_location(chat_id, location=attachment, **params)
        elif isinstance(attachment, telegram.PassportData):
            bad_type = '不支持通行证类型'
        elif isinstance(attachment, tuple) and isinstance(attachment[0], telegram.PhotoSize):
            sent_msg = await context.bot.send_photo(chat_id, attachment[0].file_id, caption=update.message.caption_html, parse_mode='HTML', **params)
        elif isinstance(attachment, telegram.Poll):
            bad_type = '不支持投票类型'
        elif isinstance(attachment, telegram.Sticker):
            sent_msg = await context.bot.send_sticker(chat_id, attachment, **params)
        elif isinstance(attachment, telegram.Story):
            bad_type= '不支持故事类型'
        elif isinstance(attachment, telegram.SuccessfulPayment):
            bad_type = '不支持支付类型'
        elif isinstance(attachment, telegram.Venue):
            sent_msg = await context.bot.send_venue(chat_id, venue=attachment, **params)
        elif isinstance(attachment, telegram.Video):
            sent_msg = await context.bot.send_video(chat_id, attachment, **params)
        elif isinstance(attachment, telegram.VideoNote):
            sent_msg = await context.bot.send_video_note(chat_id, attachment, **params)
        elif isinstance(attachment, telegram.Voice):
            sent_msg = await context.bot.send_voice(chat_id, attachment, **params)
        if bad_type:
            await update.message.reply_html(f"{bad_type}。请更换重新发送。（支持常用的文字、图片、音频、视频、文件等类型）")

        context.bot_data[f'u2a|{user_id}|{sent_msg.id}'] = update.message.id
        context.bot_data[f'a2u|{user_id}|{update.message.id}'] = sent_msg.message_id

    except Exception as e:
        await update.message.reply_html(f"发送失败: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(f"Exception while handling an update: {context.error} ")
    logger.debug(f"Exception detail is :", exc_info=context.error)

if __name__ == '__main__':
    pickle_persistence = PicklePersistence(filepath=f"./assets/{app_name}.pickle")
    application = ApplicationBuilder().token(bot_token).persistence(persistence=pickle_persistence).build()

    application.add_handler(CommandHandler('start', start, filters.ChatType.PRIVATE))
    application.add_handler(MessageHandler(~filters.COMMAND & filters.ChatType.PRIVATE, forwarding_message_u2a))
    application.add_handler(MessageHandler(filters.Chat([admin_group_id]), forwarding_message_a2u))
    application.add_handler(CommandHandler('send_media_group', send_media_group, filters.ChatType.PRIVATE | filters.Chat([admin_group_id])))


    application.add_error_handler(error_handler)
    application.run_polling()  

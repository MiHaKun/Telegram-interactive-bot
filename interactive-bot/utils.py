from . import logger, api_id, api_hash, bot_token, app_name, welcome_message, admin_group_id, admin_user_id
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaAudio, InputMediaDocument, InputMediaPhoto ,InputMediaVideo, User
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters, PicklePersistence, ConversationHandler
from telegram.helpers import create_deep_linked_url,mention_html
import telegram 



async def send_contact_card(chat_id, message_thread_id, user: User, update: Update, context: ContextTypes):
    buttons = []
    buttons.append([InlineKeyboardButton(f"{'🏆 高级会员' if user.is_premium else '✈️ 普通会员' }", url=f"https://github.com/MiHaKun/Telegram-interactive-bot")])
    if user.username:
        buttons.append([InlineKeyboardButton("👤 直接联络", url=f"https://t.me/{user.username}")])

    user_photo = await context.bot.get_user_profile_photos(user.id)

    if user_photo.total_count:
        pic = user_photo.photos[0][-1].file_id
        await context.bot.send_photo(chat_id,photo=pic, 
                                    caption=f"👤 {mention_html(user.id, user.first_name)}\n\n📱 {user.id}\n\n🔗 @{user.username if user.username else '无'}",
                                    message_thread_id=message_thread_id, reply_markup=InlineKeyboardMarkup(buttons),
                                    parse_mode='HTML')
    else:
        await context.bot.send_contact(chat_id, phone_number='11111', first_name=user.first_name, last_name=user.last_name, 
                                     message_thread_id=message_thread_id, 
                                     reply_markup=InlineKeyboardMarkup(buttons)
                                     )
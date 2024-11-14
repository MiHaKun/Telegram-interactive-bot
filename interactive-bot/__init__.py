import pkg_resources
import os
import sys
import json
import logging
from dotenv import load_dotenv


# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s- %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("log.txt")],
)
logging.getLogger("httpx").setLevel(logging.ERROR)
current_package = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(current_package)

# 读取配置文件
load_dotenv()
bot_token = os.getenv("BOT_TOKEN") or exit("BOT_TOKEN 未填写")
app_name = os.getenv("APP_NAME") or exit("APP_NAME 未填写")
welcome_message = os.getenv("WELCOME_MESSAGE") or "欢迎使用本机器人"
try:
    admin_group_id = int(os.getenv("ADMIN_GROUP_ID")) or exit("ADMIN_GROUP 未填写")
    admin_user_ids = [
        int(x.strip()) for x in os.getenv("ADMIN_USER_IDS").split(",")
    ] or exit("ADMIN_USER_IDS 未填写")
except ValueError:
    exit("ADMIN_GROUP_ID or ADMIN_USER_IDS 应该是数字\n其中ADMIN_USER_IDS是以“,”分隔")


is_delete_topic_as_ban_forever = os.getenv("DELETE_TOPIC_AS_FOREVER_BAN") == "TRUE"
is_delete_user_messages = os.getenv("DELETE_USER_MESSAGE_ON_CLEAR_CMD") == "TRUE"
disable_captcha = os.getenv("DISABLE_CAPTCHA") == "TRUE"
message_interval = int(os.getenv("MESSAGE_INTERVAL", 5))

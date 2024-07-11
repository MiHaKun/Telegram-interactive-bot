import pkg_resources
import os
import sys
import json
import logging
from dotenv import load_dotenv


# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s- %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('log.txt')
    ]
)
logging.getLogger("httpx").setLevel(logging.ERROR)
current_package = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(current_package)

# 读取配置文件
load_dotenv()
api_id = os.getenv('API_ID') or exit('API_ID 未填写')
api_hash = os.getenv('API_HASH') or exit('API_HASH 未填写')
bot_token = os.getenv('BOT_TOKEN') or exit('BOT_TOKEN 未填写')
app_name = os.getenv('APP_NAME') or exit('APP_NAME 未填写')
welcome_message = os.getenv('WELCOME_MESSAGE') or '欢迎使用本机器人'
try:
    admin_group_id = int(os.getenv('ADMIN_GROUP_ID')) or exit('ADMIN_GROUP 未填写')
    admin_user_id = int(os.getenv('ADMIN_USER_ID')) or exit('ADMIN_USER 未填写')
except ValueError:
    exit('ADMIN_GROUP_ID or ADMIN_USER_ID 应该是数字')


is_delete_topic_as_ban_forever = os.getenv('DELETE_TOPIC_AS_FOREVER_BAN') == "1" 

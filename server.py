from fastapi import FastAPI

app = FastAPI()

@app.get('/ping')
async def ping():
    return {'status': 'ok'}

from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, Body
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
import asyncio
from telegram import Bot as TelegramBot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ReactionEmoji
from openai import AsyncOpenAI
import secrets
import string
import urllib.parse
import re

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Groq Configuration
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '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')
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Main Bot Configuration
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN', '8494651263:AAE5FE0keK5-z7i7OuTEfOHEhpfutz6rrnk')
MAIN_CHANNEL = '@aiGeminator'
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '0'))

# Image Generation Configuration
IMAGE_GENERATION_PRICE_API = 50.0  # Price for API key owner
IMAGE_GENERATION_PRICE_USER = 70.0  # Price for bot users

# Keywords for detecting image generation requests
IMAGE_KEYWORDS = [
    'عکس بساز', 'یه عکس', 'یک عکس', 'تولید عکس', 'ساخت عکس',
    'عکس بده', 'عکس بفرست', 'عکس درست کن', 'تصویر بساز', 'تصویر درست کن',
    'photo', 'image', 'picture', 'generate image', 'create image',
    'make image', 'draw', 'عکسی', 'تصویری', 'نقاشی', 'طراحی'
]

# Global bot applications storage
bot_applications: Dict[str, Application] = {}

# Global main bot instance
main_bot_instance: Optional[TelegramBot] = None

# Cache for channel membership checks
membership_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 300

# ============ Models ============

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    telegram_id: int
    username: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class APIKey(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str
    user_telegram_id: int
    balance: float = 10000.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BotConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bot_token: str
    bot_name: str
    bot_username: Optional[str] = None
    owner_telegram_id: int
    channel_id: str
    api_key: str
    message_price: float = 10.0
    welcome_bonus: float = 500.0
    main_channel_locked: bool = True
    card_number: Optional[str] = "6219861865900301"
    card_holder: Optional[str] = "محمد وظیفه دان"
    enable_card_payment: bool = True
    enable_zarinpal: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "running"

class BotUser(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bot_id: str
    telegram_id: int
    username: Optional[str] = None
    balance: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bot_id: str
    user_telegram_id: int
    role: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Transaction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    amount: float
    user_telegram_id: Optional[int] = None
    bot_id: Optional[str] = None
    api_key: Optional[str] = None
    description: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bot_id: str
    user_telegram_id: int
    amount: float
    receipt_photo: Optional[str] = None
    message: Optional[str] = None
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    status: str = "pending"
    rejection_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class APIKeyChargeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_telegram_id: int
    amount: float
    receipt_photo: Optional[str] = None
    message: Optional[str] = None
    message_id: Optional[int] = None
    chat_id: Optional[int] = None
    admin_message_id: Optional[int] = None
    status: str = "pending"
    rejection_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ============ API Routes ============

@api_router.get("/")
async def root():
    return {"message": "AI Bot Factory API"}

@api_router.post("/groq/chat")
async def groq_chat(data: Dict[str, Any]):
    """Chat with Groq API"""
    try:
        messages = data.get('messages', [])
        api_key = data.get('api_key', GROQ_API_KEY)

        client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL)

        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            stream=False
        )

        return {
            "success": True,
            "content": response.choices[0].message.content
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@api_router.post("/apikeys/create")
async def create_api_key(telegram_id: int):
    """Create a new API key for user"""
    try:
        existing = await db.api_keys.find_one({"user_telegram_id": telegram_id})
        if existing:
            return {"success": False, "error": "You already have an API key"}

        key = 'botmaker_' + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

        api_key = APIKey(
            key=key,
            user_telegram_id=telegram_id,
            balance=10000.0
        )

        doc = api_key.model_dump()
        doc['created_at'] = doc['created_at'].isoformat()

        await db.api_keys.insert_one(doc)

        return {"success": True, "api_key": key, "balance": 10000.0}
    except Exception as e:
        return {"success": False, "error": str(e)}

@api_router.get("/apikeys/info/{telegram_id}")
async def get_api_key_info(telegram_id: int):
    """Get API key information"""
    api_key = await db.api_keys.find_one({"user_telegram_id": telegram_id}, {"_id": 0})
    if not api_key:
        return {"success": False, "error": "No API key found"}
    return {"success": True, "data": api_key}

@api_router.post("/bots/create")
async def create_bot(config: BotConfig, background_tasks: BackgroundTasks):
    """Create a new bot"""
    try:
        api_key_doc = await db.api_keys.find_one({"key": config.api_key})
        if not api_key_doc:
            return {"success": False, "error": "Invalid API key"}

        try:
            test_bot = TelegramBot(token=config.bot_token)
            bot_info = await test_bot.get_me()
            config.bot_username = bot_info.username
            await test_bot.close()
        except Exception as e:
            return {"success": False, "error": f"Invalid bot token: {str(e)}"}

        doc = config.model_dump()
        doc['created_at'] = doc['created_at'].isoformat()

        await db.bots.insert_one(doc)

        background_tasks.add_task(start_user_bot, config.id, config.bot_token, config)

        return {
            "success": True,
            "bot_id": config.id,
            "bot_username": bot_info.username,
            "message": "Bot created and started successfully"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@api_router.get("/bots/list/{telegram_id}")
async def list_bots(telegram_id: int):
    """List all bots for a user"""
    bots = await db.bots.find({"owner_telegram_id": telegram_id}, {"_id": 0}).to_list(1000)
    return {"success": True, "bots": bots}

@api_router.delete("/bots/delete/{bot_id}")
async def delete_bot(bot_id: str):
    """Delete a bot"""
    try:
        if bot_id in bot_applications:
            app = bot_applications[bot_id]
            await app.stop()
            await app.shutdown()
            del bot_applications[bot_id]

        await db.bots.delete_one({"id": bot_id})
        await db.bot_users.delete_many({"bot_id": bot_id})
        await db.messages.delete_many({"bot_id": bot_id})

        return {"success": True, "message": "Bot deleted successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============ Helper Functions ============

def get_cached_membership(user_id: int, channel: str) -> Optional[bool]:
    """Get cached membership result"""
    cache_key = f"{user_id}_{channel}"
    if cache_key in membership_cache:
        cached = membership_cache[cache_key]
        elapsed = (datetime.now(timezone.utc) - cached['timestamp']).total_seconds()
        if elapsed < CACHE_TTL_SECONDS:
            return cached['is_member']
        else:
            del membership_cache[cache_key]
    return None

def set_cached_membership(user_id: int, channel: str, is_member: bool):
    """Cache membership result"""
    cache_key = f"{user_id}_{channel}"
    membership_cache[cache_key] = {
        'is_member': is_member,
        'timestamp': datetime.now(timezone.utc)
    }

async def get_main_bot_instance() -> TelegramBot:
    """Get or create the global main bot instance"""
    global main_bot_instance
    if main_bot_instance is None:
        main_bot_instance = TelegramBot(token=MAIN_BOT_TOKEN)
    return main_bot_instance

async def check_channel_membership(user_id: int, channel: str, bot: TelegramBot) -> bool:
    """Check if user is member of channel"""
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        is_member = member.status in ['member', 'administrator', 'creator']
        return is_member
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

async def check_channel_membership_cached(user_id: int, channel: str) -> bool:
    """Check channel membership with caching"""
    cached = get_cached_membership(user_id, channel)
    if cached is not None:
        return cached

    try:
        bot = await get_main_bot_instance()
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        is_member = member.status in ['member', 'administrator', 'creator']
        set_cached_membership(user_id, channel, is_member)
        return is_member
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

async def check_main_channel_via_api(user_id: int) -> bool:
    """Check main channel membership"""
    cached = get_cached_membership(user_id, MAIN_CHANNEL)
    if cached is not None:
        return cached

    try:
        bot = await get_main_bot_instance()
        member = await bot.get_chat_member(chat_id=MAIN_CHANNEL, user_id=user_id)
        is_member = member.status in ['member', 'administrator', 'creator']
        set_cached_membership(user_id, MAIN_CHANNEL, is_member)
        return is_member
    except Exception as e:
        logger.error(f"Error checking main channel: {e}")
        return False

async def cleanup_old_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, max_messages: int = 55):
    """حذف پیام‌های قدیمی اگر بیش از حد مشخص باشند"""
    try:
        # این تابع می‌تواند گسترش یابد برای حذف پیام‌های قدیمی
        pass
    except Exception as e:
        logger.error(f"Error cleaning up messages: {e}")

# ============ Main Bot Functions ============

async def start_main_bot():
    """Start the main bot maker bot"""
    application = Application.builder().token(MAIN_BOT_TOKEN).build()

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Log user_id for debugging
        logger.info(f"User {user_id} started the main bot. ADMIN_USER_ID is {ADMIN_USER_ID}")

        is_member = await check_channel_membership(user_id, MAIN_CHANNEL, context.bot)
        if not is_member:
            keyboard = [[InlineKeyboardButton("🔗 عضویت در کانال", url=f"https://t.me/{MAIN_CHANNEL.replace('@', '')}")]]
            keyboard.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")])
            await update.message.reply_text(
                f"سلام! 👋\n\nبرای استفاده از ربات، لطفاً ابتدا در کانال {MAIN_CHANNEL} عضو شوید.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

        user = User(telegram_id=user_id, username=update.effective_user.username)
        doc = user.model_dump()
        doc['created_at'] = doc['created_at'].isoformat()
        await db.users.update_one({"telegram_id": user_id}, {"$set": doc}, upsert=True)

        bots = await db.bots.find({"owner_telegram_id": user_id}).to_list(10)

        keyboard = [
            [InlineKeyboardButton("🤖 ساخت ربات", callback_data="create_bot")],
            [InlineKeyboardButton("🔑 مدیریت API KEY", callback_data="manage_apikey")],
            [InlineKeyboardButton("📖 راهنما", callback_data="help")]
        ]

        if bots:
            keyboard.insert(1, [InlineKeyboardButton("🤖 ربات‌های من", callback_data="my_bots")])

        if user_id == ADMIN_USER_ID:
            keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

        await update.message.reply_text(
            "🎉 خوش آمدید به رباتساز جمیناتور!\n\n"
            "با این ربات می‌توانید ربات‌های هوش مصنوعی خودتان را بسازید.\n\n"
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id

        if query.data == "check_membership":
            is_member = await check_channel_membership(user_id, MAIN_CHANNEL, context.bot)
            if is_member:
                user = User(telegram_id=user_id, username=update.effective_user.username)
                doc = user.model_dump()
                doc['created_at'] = doc['created_at'].isoformat()
                await db.users.update_one({"telegram_id": user_id}, {"$set": doc}, upsert=True)

                bots = await db.bots.find({"owner_telegram_id": user_id}).to_list(10)
                keyboard = [
                    [InlineKeyboardButton("🤖 ساخت ربات", callback_data="create_bot")],
                    [InlineKeyboardButton("🔑 مدیریت API KEY", callback_data="manage_apikey")],
                    [InlineKeyboardButton("📖 راهنما", callback_data="help")]
                ]
                if bots:
                    keyboard.insert(1, [InlineKeyboardButton("🤖 ربات‌های من", callback_data="my_bots")])

                if user_id == ADMIN_USER_ID:
                    keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

                await query.edit_message_text(
                    "🎉 خوش آمدید به رباتساز جمیناتور!\n\n"
                    "با این ربات می‌توانید ربات‌های هوش مصنوعی خودتان را بسازید.\n\n"
                    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await query.answer("⚠️ لطفاً ابتدا در کانال عضو شوید.", show_alert=True)

        elif query.data == "manage_apikey":
            api_key = await db.api_keys.find_one({"user_telegram_id": user_id})
            if not api_key:
                keyboard = [
                    [InlineKeyboardButton("✨ ساخت API KEY", callback_data="create_apikey")],
                    [InlineKeyboardButton("💰 خرید شارژ API KEY", callback_data="buy_api_credit")]
                ]
                await query.edit_message_text(
                    "🔑 مدیریت API KEY\n\n"
                    "شما هنوز API KEY ندارید.\n"
                    "با ساخت API KEY، 10,000 تومان شارژ رایگان دریافت می‌کنید! 🎁",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                keyboard = [
                    [InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_api_credit")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
                ]
                await query.edit_message_text(
                    f"🔑 اطلاعات API KEY شما:\n\n"
                    f"🔑 کلید: `{api_key['key']}`\n"
                    f"💰 موجودی: {api_key['balance']:,.0f} تومان\n\n"
                    f"⏰ تاریخ ساخت: {api_key['created_at']}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif query.data == "buy_api_credit":
            context.user_data['buying_api_credit'] = True
            await query.edit_message_text(
                "💰 خرید شارژ API KEY\n\n"
                f"💳 شماره کارت: `6219861865900301`\n"
                f"👤 به نام: محمد وظیفه دان\n\n"
                "لطفاً مبلغ مورد نظر را به شماره کارت بالا واریز کنید و سپس:\n"
                "1️⃣ مبلغ واریزی را ارسال کنید (فقط عدد، به تومان)\n\n"
                "مثال: 50000",
                parse_mode='Markdown'
            )

        elif query.data == "create_apikey":
            api_key = await db.api_keys.find_one({"user_telegram_id": user_id})
            if api_key:
                await query.answer("شما قبلاً API KEY ساخته‌اید!", show_alert=True)
                return

            key = 'botmaker_' + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            api_key = APIKey(key=key, user_telegram_id=user_id, balance=10000.0)
            doc = api_key.model_dump()
            doc['created_at'] = doc['created_at'].isoformat()
            await db.api_keys.insert_one(doc)

            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]
            await query.edit_message_text(
                f"✅ API KEY شما با موفقیت ساخته شد!\n\n"
                f"🔑 کلید: `{key}`\n"
                f"💰 موجودی اولیه: 10,000 تومان 🎁\n\n"
                f"⚠️ این کلید را در جایی امنی نگهداری کنید.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "create_bot":
            api_key = await db.api_keys.find_one({"user_telegram_id": user_id})
            if not api_key:
                keyboard = [[InlineKeyboardButton("✨ ساخت API KEY", callback_data="create_apikey")]]
                await query.edit_message_text(
                    "⚠️ برای ساخت ربات، ابتدا باید API KEY بسازید.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            context.user_data['creating_bot'] = True
            context.user_data['bot_data'] = {}
            
            keyboard = [[InlineKeyboardButton("❌ لغو ساخت", callback_data="cancel_bot_creation")]]
            await query.edit_message_text(
                "🤖 ساخت ربات جدید\n\n"
                "لطفاً نام ربات خود را وارد کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "my_bots":
            bots = await db.bots.find({"owner_telegram_id": user_id}).to_list(100)
            if not bots:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]
                await query.edit_message_text(
                    "شما هنوز ربات نساخته‌اید.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                text = "🤖 ربات‌های شما:\n\n"
                keyboard = []
                for bot in bots:
                    text += f"• {bot['bot_name']} - {bot['status']}\n"
                    keyboard.append([InlineKeyboardButton(f"⚙️ {bot['bot_name']}", callback_data=f"bot_detail_{bot['id']}")])
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("bot_detail_"):
            bot_id = query.data.replace("bot_detail_", "")
            bot = await db.bots.find_one({"id": bot_id})
            if bot:
                keyboard = [
                    [InlineKeyboardButton("❌ حذف ربات", callback_data=f"delete_bot_{bot_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="my_bots")]
                ]
                await query.edit_message_text(
                    f"🤖 جزئیات ربات: {bot['bot_name']}\n\n"
                    f"🔑 توکن: `{bot['bot_token'][:20]}...`\n"
                    f"📢 کانال: {bot['channel_id']}\n"
                    f"💰 قیمت هر پیام: {bot['message_price']} تومان\n"
                    f"🔒 قفل کانال اصلی: {'فعال' if bot['main_channel_locked'] else 'غیرفعال'}\n"
                    f"📊 وضعیت: {bot['status']}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif query.data.startswith("delete_bot_"):
            bot_id = query.data.replace("delete_bot_", "")

            # اگر ربات در حال اجراست، آن را متوقف کنیم
            if bot_id in bot_applications:
                app = bot_applications[bot_id]
                try:
                    # توقف صحیح ربات برای جلوگیری از Flood control
                    if hasattr(app, 'updater') and app.updater:
                        await app.updater.stop()
                    await app.stop()
                    await app.shutdown()
                    
                    # صبر کردن برای اطمینان از آزاد شدن منابع
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Error stopping bot {bot_id}: {e}")
                finally:
                    del bot_applications[bot_id]
                    # صبر اضافی برای جلوگیری از Flood control
                    await asyncio.sleep(1)

            await db.bots.delete_one({"id": bot_id})
            await db.bot_users.delete_many({"bot_id": bot_id})
            await db.messages.delete_many({"bot_id": bot_id})
            await db.payment_requests.delete_many({"bot_id": bot_id})

            await query.answer("✅ ربات حذف شد و از سرور خاموش شد.", show_alert=True)
            await query.edit_message_text(
                "✅ ربات با موفقیت حذف و از سرور خاموش شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="my_bots")]])
            )

        elif query.data == "help":
            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]]
            await query.edit_message_text(
                "📖 راهنمای استفاده از رباتساز جمیناتور\n\n"
                "1️⃣ ابتدا یک API KEY بسازید و 10,000 تومان شارژ رایگان دریافت کنید.\n\n"
                "2️⃣ با استفاده از BotFather در تلگرام، یک ربات جدید بسازید و توکن آن را دریافت کنید.\n\n"
                "3️⃣ از منوی ساخت ربات، اطلاعات ربات خود را وارد کنید:\n"
                "   • نام ربات\n"
                "   • آیدی کانال (مثال: @mychannel)\n"
                "   • توکن ربات\n\n"
                "4️⃣ ربات شما به صورت خودکار با آیدی شما ساخته می‌شود و کاربران می‌توانند با آن چت کنند.\n\n"
                "5️⃣ برای هر پیام کاربران، از موجودی آن‌ها کسر می‌شود و به موجودی API KEY شما اضافه می‌شود.\n\n"
                "💡 نکته: کاربران ربات شما باید برای چت کردن، شارژ حساب کنند.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "admin_panel":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            keyboard = [
                [InlineKeyboardButton("📊 آمار کلی", callback_data="admin_stats")],
                [InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_manage_users")],
                [InlineKeyboardButton("🤖 مدیریت ربات‌ها", callback_data="admin_manage_bots")],
                [InlineKeyboardButton("💰 درخواست‌های شارژ API KEY", callback_data="admin_apikey_requests")],
                [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast_menu")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
            ]

            await query.edit_message_text(
                "👨‍💼 پنل مدیریت ربات جمیناتور\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "admin_stats":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            total_users = await db.users.count_documents({})
            total_bots = await db.bots.count_documents({})
            total_api_keys = await db.api_keys.count_documents({})
            pending_payments = await db.payment_requests.count_documents({"status": "pending"})

            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]

            await query.edit_message_text(
                f"📊 آمار کلی سیستم\n\n"
                f"👥 تعداد کاربران: {total_users:,}\n"
                f"🤖 تعداد ربات‌ها: {total_bots:,}\n"
                f"🔑 تعداد API KEY‌ها: {total_api_keys:,}\n"
                f"💰 درخواست‌های پرداخت در انتظار: {pending_payments:,}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "admin_payments":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            payments = await db.payment_requests.find({"status": "pending"}).to_list(10)

            if not payments:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
                await query.edit_message_text(
                    "💰 درخواست‌های پرداخت\n\n"
                    "هیچ درخواست پرداخت در انتظاری وجود ندارد.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                text = "💰 درخواست‌های پرداخت در انتظار:\n\n"
                keyboard = []

                for payment in payments[:5]:
                    bot = await db.bots.find_one({"id": payment['bot_id']})
                    bot_name = bot['bot_name'] if bot else "نامشخص"
                    text += f"• {payment['amount']:,} تومان - {bot_name}\n"
                    keyboard.append([
                        InlineKeyboardButton(f"✅ تایید {payment['amount']:,}", callback_data=f"approve_payment_{payment['id']}"),
                        InlineKeyboardButton("❌ رد", callback_data=f"reject_payment_{payment['id']}")
                    ])

                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])

                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data == "admin_apikey_requests":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            requests = await db.apikey_charge_requests.find({"status": "pending"}).to_list(10)

            if not requests:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
                await query.edit_message_text(
                    "💰 درخواست‌های شارژ API KEY\n\n"
                    "هیچ درخواستی در انتظار نیست.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                text = "💰 درخواست‌های شارژ API KEY:\n\n"
                keyboard = []

                for req in requests[:5]:
                    text += f"• {req['amount']:,} تومان - کاربر {req['user_telegram_id']}\n"
                    keyboard.append([
                        InlineKeyboardButton(f"✅ تایید {req['amount']:,}", callback_data=f"approve_apikey_{req['id']}"),
                        InlineKeyboardButton("❌ رد", callback_data=f"reject_apikey_{req['id']}")
                    ])

                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])

                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("approve_payment_"):
            # Check if this is from main bot admin or bot owner
            payment_id = query.data.replace("approve_payment_", "")
            payment = await db.payment_requests.find_one({"id": payment_id})
            
            if not payment:
                await query.answer("❌ درخواست پرداخت یافت نشد.", show_alert=True)
                return

            bot_config = await db.bots.find_one({"id": payment['bot_id']})
            
            # Check if user is the bot owner (for user bots) or main admin (for main bot)
            if user_id != bot_config['owner_telegram_id'] and user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ندارید.", show_alert=True)
                return

            # Update balance
            await db.bot_users.update_one(
                {"bot_id": payment['bot_id'], "telegram_id": payment['user_telegram_id']},
                {"$inc": {"balance": payment['amount']}}
            )

            # Update payment status
            await db.payment_requests.update_one(
                {"id": payment_id},
                {"$set": {"status": "approved"}}
            )

            # Send message to user
            if bot_config and payment['bot_id'] in bot_applications:
                bot_app = bot_applications[payment['bot_id']]
                try:
                    # Create keyboard with return button
                    return_keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]]
                    
                    await bot_app.bot.send_message(
                        chat_id=payment['user_telegram_id'],
                        text=f"✅ پرداخت شما با موفقیت تایید شد!\n\n"
                             f"💰 مبلغ: {payment['amount']:,} تومان\n"
                             f"✨ موجودی به حساب شما اضافه شد.",
                        reply_markup=InlineKeyboardMarkup(return_keyboard)
                    )
                    
                    # Delete previous receipt message
                    if payment.get('message_id') and payment.get('chat_id'):
                        try:
                            await bot_app.bot.delete_message(
                                chat_id=payment['chat_id'],
                                message_id=payment['message_id']
                            )
                        except:
                            pass
                except:
                    pass

            # Remove buttons from admin message (don't delete the photo)
            await query.answer("✅ پرداخت تایید شد.", show_alert=True)
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except:
                pass

        elif query.data.startswith("reject_payment_"):
            payment_id = query.data.replace("reject_payment_", "")
            payment = await db.payment_requests.find_one({"id": payment_id})
            
            if not payment:
                await query.answer("❌ درخواست پرداخت یافت نشد.", show_alert=True)
                return
            
            bot_config = await db.bots.find_one({"id": payment['bot_id']})
            
            # Check if user is the bot owner or main admin
            if user_id != bot_config['owner_telegram_id'] and user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ندارید.", show_alert=True)
                return

            context.user_data['rejecting_payment_id'] = payment_id
            context.user_data['rejecting_payment_message_id'] = query.message.message_id

            # Delete the message with buttons
            try:
                await query.message.delete()
            except:
                pass
            
            # Send new message asking for reason
            keyboard = [[InlineKeyboardButton("🔙 انصراف", callback_data="admin_panel")]]
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ رد کردن درخواست پرداخت\n\n"
                     "لطفاً دلیل رد کردن را وارد کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data.startswith("approve_apikey_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            request_id = query.data.replace("approve_apikey_", "")
            req = await db.apikey_charge_requests.find_one({"id": request_id})

            if req:
                await db.api_keys.update_one(
                    {"user_telegram_id": req['user_telegram_id']},
                    {"$inc": {"balance": req['amount']}}
                )

                await db.apikey_charge_requests.update_one(
                    {"id": request_id},
                    {"$set": {"status": "approved"}}
                )

                try:
                    # ارسال پیام به کاربر
                    await context.bot.send_message(
                        chat_id=req['user_telegram_id'],
                        text=f"✅ درخواست شارژ API KEY شما تایید شد!\n\n"
                             f"💰 مبلغ: {req['amount']:,} تومان\n"
                             f"✨ موجودی به حساب شما اضافه شد."
                    )
                except:
                    pass

                # حذف دکمه‌های زیر رسید (نه خود رسید)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except:
                    pass

                await query.answer("✅ درخواست تایید شد.", show_alert=True)
            else:
                await query.answer("❌ درخواست یافت نشد.", show_alert=True)

        elif query.data.startswith("reject_apikey_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            request_id = query.data.replace("reject_apikey_", "")
            context.user_data['rejecting_apikey_id'] = request_id

            # Delete the message with buttons
            try:
                await query.message.delete()
            except:
                pass
            
            # Send new message asking for reason
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ رد کردن درخواست شارژ API KEY\n\n"
                     "لطفاً دلیل رد کردن را وارد کنید:"
            )

        # ============ مدیریت کاربران ============
        
        elif query.data == "admin_manage_users":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            keyboard = [
                [InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_list_users")],
                [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search_user")],
                [InlineKeyboardButton("💰 افزایش اعتبار کاربر", callback_data="admin_increase_credit")],
                [InlineKeyboardButton("📉 کاهش اعتبار کاربر", callback_data="admin_decrease_credit")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]

            await query.edit_message_text(
                "👥 مدیریت کاربران\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "admin_list_users":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            users = await db.users.find({}, {"_id": 0}).sort("created_at", -1).to_list(10)
            
            if not users:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_users")]]
                await query.edit_message_text(
                    "👥 لیست کاربران\n\n"
                    "هیچ کاربری یافت نشد.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                text = "👥 آخرین کاربران سیستم:\n\n"
                keyboard = []
                
                for u in users:
                    api_key = await db.api_keys.find_one({"user_telegram_id": u['telegram_id']})
                    balance = api_key['balance'] if api_key else 0
                    username = u.get('username', 'بدون نام')
                    text += f"• ID: {u['telegram_id']} | @{username}\n"
                    text += f"  💰 موجودی API: {balance:,.0f} تومان\n\n"
                    
                    keyboard.append([
                        InlineKeyboardButton(f"👤 {username}", callback_data=f"admin_user_detail_{u['telegram_id']}")
                    ])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_users")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("admin_user_detail_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            target_user_id = int(query.data.replace("admin_user_detail_", ""))
            user_data = await db.users.find_one({"telegram_id": target_user_id})
            api_key = await db.api_keys.find_one({"user_telegram_id": target_user_id})
            user_bots = await db.bots.count_documents({"owner_telegram_id": target_user_id})

            if not user_data:
                await query.answer("❌ کاربر یافت نشد.", show_alert=True)
                return

            balance = api_key['balance'] if api_key else 0
            username = user_data.get('username', 'بدون نام')

            keyboard = [
                [
                    InlineKeyboardButton("➕ افزایش اعتبار", callback_data=f"admin_add_credit_{target_user_id}"),
                    InlineKeyboardButton("➖ کاهش اعتبار", callback_data=f"admin_sub_credit_{target_user_id}")
                ],
                [InlineKeyboardButton("📩 ارسال پیام", callback_data=f"admin_send_msg_{target_user_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_list_users")]
            ]

            await query.edit_message_text(
                f"👤 جزئیات کاربر\n\n"
                f"🆔 Telegram ID: {target_user_id}\n"
                f"👤 نام کاربری: @{username}\n"
                f"💰 موجودی API: {balance:,.0f} تومان\n"
                f"🤖 تعداد ربات‌ها: {user_bots}\n"
                f"📅 تاریخ عضویت: {user_data.get('created_at', 'نامشخص')}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data.startswith("admin_add_credit_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            target_user_id = int(query.data.replace("admin_add_credit_", ""))
            context.user_data['admin_credit_action'] = 'add'
            context.user_data['admin_credit_user'] = target_user_id

            await query.edit_message_text(
                f"➕ افزایش اعتبار کاربر {target_user_id}\n\n"
                "لطفاً مبلغی که می‌خواهید اضافه کنید را وارد کنید (به تومان):\n\n"
                "مثال: 50000"
            )

        elif query.data.startswith("admin_sub_credit_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            target_user_id = int(query.data.replace("admin_sub_credit_", ""))
            context.user_data['admin_credit_action'] = 'subtract'
            context.user_data['admin_credit_user'] = target_user_id

            await query.edit_message_text(
                f"➖ کاهش اعتبار کاربر {target_user_id}\n\n"
                "لطفاً مبلغی که می‌خواهید کم کنید را وارد کنید (به تومان):\n\n"
                "مثال: 10000"
            )

        elif query.data.startswith("admin_send_msg_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            target_user_id = int(query.data.replace("admin_send_msg_", ""))
            context.user_data['admin_sending_msg'] = True
            context.user_data['admin_msg_target'] = target_user_id

            await query.edit_message_text(
                f"📩 ارسال پیام به کاربر {target_user_id}\n\n"
                "لطفاً پیام خود را وارد کنید:"
            )

        elif query.data == "admin_search_user":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_searching_user'] = True
            await query.edit_message_text(
                "🔍 جستجوی کاربر\n\n"
                "لطفاً Telegram ID کاربر را وارد کنید:"
            )

        elif query.data == "admin_increase_credit":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_credit_action'] = 'add'
            await query.edit_message_text(
                "➕ افزایش اعتبار کاربر\n\n"
                "لطفاً Telegram ID کاربر را وارد کنید:\n\n"
                "مثال: 123456789"
            )

        elif query.data == "admin_decrease_credit":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_credit_action'] = 'subtract'
            await query.edit_message_text(
                "➖ کاهش اعتبار کاربر\n\n"
                "لطفاً Telegram ID کاربر را وارد کنید:\n\n"
                "مثال: 123456789"
            )

        # ============ مدیریت ربات‌ها ============

        elif query.data == "admin_manage_bots":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            keyboard = [
                [InlineKeyboardButton("🤖 لیست تمام ربات‌ها", callback_data="admin_list_all_bots")],
                [InlineKeyboardButton("📢 ارسال پیام به ربات‌ها", callback_data="admin_send_to_bots")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]

            await query.edit_message_text(
                "🤖 مدیریت ربات‌ها\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "admin_list_all_bots":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            bots = await db.bots.find({}, {"_id": 0}).sort("created_at", -1).to_list(15)
            
            if not bots:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_bots")]]
                await query.edit_message_text(
                    "🤖 لیست ربات‌ها\n\n"
                    "هیچ رباتی یافت نشد.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                text = "🤖 لیست تمام ربات‌ها:\n\n"
                keyboard = []
                
                for bot in bots:
                    bot_users_count = await db.bot_users.count_documents({"bot_id": bot['id']})
                    text += f"• {bot['bot_name']} (@{bot.get('bot_username', 'نامشخص')})\n"
                    text += f"  👥 کاربران: {bot_users_count} | وضعیت: {bot['status']}\n\n"
                    
                    keyboard.append([
                        InlineKeyboardButton(f"⚙️ {bot['bot_name']}", callback_data=f"admin_bot_detail_{bot['id']}")
                    ])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_bots")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("admin_bot_detail_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            bot_id = query.data.replace("admin_bot_detail_", "")
            bot = await db.bots.find_one({"id": bot_id})
            
            if not bot:
                await query.answer("❌ ربات یافت نشد.", show_alert=True)
                return

            bot_users_count = await db.bot_users.count_documents({"bot_id": bot_id})
            bot_messages_count = await db.messages.count_documents({"bot_id": bot_id})
            owner = await db.users.find_one({"telegram_id": bot['owner_telegram_id']})
            owner_username = owner.get('username', 'نامشخص') if owner else 'نامشخص'

            keyboard = [
                [InlineKeyboardButton("📢 ارسال پیام به کاربران ربات", callback_data=f"admin_bot_broadcast_{bot_id}")],
                [InlineKeyboardButton("❌ حذف ربات", callback_data=f"admin_delete_bot_{bot_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_list_all_bots")]
            ]

            await query.edit_message_text(
                f"🤖 جزئیات ربات\n\n"
                f"📛 نام: {bot['bot_name']}\n"
                f"🆔 یوزرنیم: @{bot.get('bot_username', 'نامشخص')}\n"
                f"👤 صاحب ربات: @{owner_username} ({bot['owner_telegram_id']})\n"
                f"📢 کانال: {bot['channel_id']}\n"
                f"👥 تعداد کاربران: {bot_users_count}\n"
                f"💬 تعداد پیام‌ها: {bot_messages_count}\n"
                f"💰 قیمت پیام: {bot['message_price']} تومان\n"
                f"📊 وضعیت: {bot['status']}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data.startswith("admin_delete_bot_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            bot_id = query.data.replace("admin_delete_bot_", "")
            
            # Stop the bot if running - با روش صحیح برای جلوگیری از Flood control
            if bot_id in bot_applications:
                app = bot_applications[bot_id]
                try:
                    if hasattr(app, 'updater') and app.updater:
                        await app.updater.stop()
                    await app.stop()
                    await app.shutdown()
                    
                    # صبر برای آزاد شدن منابع
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Error stopping bot {bot_id}: {e}")
                finally:
                    del bot_applications[bot_id]
                    await asyncio.sleep(1)

            # Delete from database
            bot = await db.bots.find_one({"id": bot_id})
            await db.bots.delete_one({"id": bot_id})
            await db.bot_users.delete_many({"bot_id": bot_id})
            await db.messages.delete_many({"bot_id": bot_id})
            await db.payment_requests.delete_many({"bot_id": bot_id})

            await query.answer("✅ ربات حذف شد.", show_alert=True)
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_list_all_bots")]]
            await query.edit_message_text(
                f"✅ ربات {bot['bot_name']} با موفقیت حذف شد.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data.startswith("admin_bot_broadcast_"):
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            bot_id = query.data.replace("admin_bot_broadcast_", "")
            context.user_data['admin_bot_broadcast'] = bot_id

            await query.edit_message_text(
                f"📢 ارسال پیام به کاربران ربات\n\n"
                "لطفاً پیام خود را وارد کنید:"
            )

        elif query.data == "admin_send_to_bots":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_broadcast_to_bot_owners'] = True

            await query.edit_message_text(
                "📢 ارسال پیام به صاحبان ربات‌ها\n\n"
                "لطفاً پیام خود را وارد کنید:"
            )

        # ============ ارسال پیام همگانی ============

        elif query.data == "admin_broadcast_menu":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            keyboard = [
                [InlineKeyboardButton("📢 ارسال به تمام کاربران", callback_data="admin_broadcast_all_users")],
                [InlineKeyboardButton("🤖 ارسال به صاحبان ربات‌ها", callback_data="admin_broadcast_bot_owners")],
                [InlineKeyboardButton("👥 ارسال به کاربران ربات‌های خاص", callback_data="admin_broadcast_bot_users")],
                [InlineKeyboardButton("🤖👥 ارسال به تمامی کاربران ربات‌ها", callback_data="admin_broadcast_all_bot_users")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]

            await query.edit_message_text(
                "📢 ارسال پیام همگانی\n\n"
                "لطفاً نوع ارسال را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "admin_broadcast_all_users":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_broadcast_all'] = True

            await query.edit_message_text(
                "📢 ارسال پیام به تمام کاربران\n\n"
                "لطفاً پیام خود را وارد کنید:"
            )

        elif query.data == "admin_broadcast_bot_owners":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_broadcast_to_bot_owners'] = True

            await query.edit_message_text(
                "📢 ارسال پیام به صاحبان ربات‌ها\n\n"
                "لطفاً پیام خود را وارد کنید:"
            )

        elif query.data == "admin_broadcast_bot_users":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            bots = await db.bots.find({}, {"_id": 0}).to_list(20)
            
            if not bots:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_broadcast_menu")]]
                await query.edit_message_text(
                    "🤖 انتخاب ربات\n\n"
                    "هیچ رباتی یافت نشد.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                text = "🤖 انتخاب ربات برای ارسال پیام:\n\n"
                keyboard = []
                
                for bot in bots:
                    bot_users_count = await db.bot_users.count_documents({"bot_id": bot['id']})
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{bot['bot_name']} ({bot_users_count} کاربر)",
                            callback_data=f"admin_bot_broadcast_{bot['id']}"
                        )
                    ])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_broadcast_menu")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data == "admin_broadcast_all_bot_users":
            if user_id != ADMIN_USER_ID:
                await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                return

            context.user_data['admin_broadcast_all_bot_users'] = True

            await query.edit_message_text(
                "🤖👥 ارسال پیام به تمامی کاربران ربات‌ها\n\n"
                "لطفاً پیام خود را وارد کنید:"
            )

        elif query.data == "cancel_bot_creation":
            # لغو ساخت ربات و پاک کردن داده‌ها
            context.user_data.clear()
            
            bots = await db.bots.find({"owner_telegram_id": user_id}).to_list(10)
            keyboard = [
                [InlineKeyboardButton("🤖 ساخت ربات", callback_data="create_bot")],
                [InlineKeyboardButton("🔑 مدیریت API KEY", callback_data="manage_apikey")],
                [InlineKeyboardButton("📖 راهنما", callback_data="help")]
            ]
            if bots:
                keyboard.insert(1, [InlineKeyboardButton("🤖 ربات‌های من", callback_data="my_bots")])

            if user_id == ADMIN_USER_ID:
                keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

            await query.edit_message_text(
                "❌ ساخت ربات لغو شد.\n\n"
                "🎉 خوش آمدید به رباتساز جمیناتور!\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "back_to_menu":
            bots = await db.bots.find({"owner_telegram_id": user_id}).to_list(10)
            keyboard = [
                [InlineKeyboardButton("🤖 ساخت ربات", callback_data="create_bot")],
                [InlineKeyboardButton("🔑 مدیریت API KEY", callback_data="manage_apikey")],
                [InlineKeyboardButton("📖 راهنما", callback_data="help")]
            ]
            if bots:
                keyboard.insert(1, [InlineKeyboardButton("🤖 ربات‌های من", callback_data="my_bots")])

            if user_id == ADMIN_USER_ID:
                keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

            await query.edit_message_text(
                "🎉 خوش آمدید به رباتساز جمیناتور!\n\n"
                "با این ربات می‌توانید ربات‌های هوش مصنوعی خودتان را بسازید.\n\n"
                "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def main_bot_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        # Handle creating bot flow
        if context.user_data.get('creating_bot'):
            bot_data = context.user_data.get('bot_data', {})
            
            # دکمه لغو ساخت
            cancel_keyboard = [[InlineKeyboardButton("❌ لغو ساخت", callback_data="cancel_bot_creation")]]
            
            if 'bot_name' not in bot_data:
                bot_data['bot_name'] = update.message.text
                context.user_data['bot_data'] = bot_data
                await update.message.reply_text(
                    "✅ نام ربات ذخیره شد.\n\n"
                    "حالا آیدی کانال خود را وارد کنید (مثال: @mychannel):",
                    reply_markup=InlineKeyboardMarkup(cancel_keyboard)
                )
            elif 'channel_id' not in bot_data:
                bot_data['channel_id'] = update.message.text
                context.user_data['bot_data'] = bot_data
                await update.message.reply_text(
                    "✅ آیدی کانال ذخیره شد.\n\n"
                    "حالا توکن ربات را وارد کنید:",
                    reply_markup=InlineKeyboardMarkup(cancel_keyboard)
                )
            elif 'bot_token' not in bot_data:
                bot_data['bot_token'] = update.message.text
                
                api_key = await db.api_keys.find_one({"user_telegram_id": user_id})
                
                bot_config = BotConfig(
                    bot_token=bot_data['bot_token'],
                    bot_name=bot_data['bot_name'],
                    owner_telegram_id=user_id,
                    channel_id=bot_data['channel_id'],
                    api_key=api_key['key']
                )
                
                try:
                    test_bot = TelegramBot(token=bot_config.bot_token)
                    bot_info = await test_bot.get_me()
                    bot_config.bot_username = bot_info.username
                    await test_bot.close()
                except Exception as e:
                    await update.message.reply_text(f"❌ توکن ربات نامعتبر است: {str(e)}")
                    context.user_data.clear()
                    return
                
                doc = bot_config.model_dump()
                doc['created_at'] = doc['created_at'].isoformat()
                await db.bots.insert_one(doc)
                
                asyncio.create_task(start_user_bot(bot_config.id, bot_config.bot_token, bot_config))
                
                keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_to_menu")]]
                await update.message.reply_text(
                    f"✅ ربات شما با موفقیت ساخته شد!\n\n"
                    f"🤖 نام: {bot_config.bot_name}\n"
                    f"🆔 یوزرنیم: @{bot_info.username}\n"
                    f"📢 کانال: {bot_config.channel_id}\n\n"
                    f"ربات شما الان آماده استفاده است!",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.clear()

        # Handle API credit purchase
        elif context.user_data.get('buying_api_credit'):
            if context.user_data.get('api_credit_step') == 'receipt':
                if update.message.photo:
                    photo = update.message.photo[-1]
                    context.user_data['api_credit_receipt'] = photo.file_id
                    
                    amount = context.user_data.get('api_credit_amount', 0)
                    
                    charge_req = APIKeyChargeRequest(
                        user_telegram_id=user_id,
                        amount=amount,
                        receipt_photo=photo.file_id,
                        message_id=update.message.message_id,
                        chat_id=update.message.chat_id,
                        status="pending"
                    )
                    doc = charge_req.model_dump()
                    doc['created_at'] = doc['created_at'].isoformat()
                    await db.apikey_charge_requests.insert_one(doc)
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ تایید", callback_data=f"approve_apikey_{charge_req.id}")],
                        [InlineKeyboardButton("❌ رد کردن", callback_data=f"reject_apikey_{charge_req.id}")]
                    ]
                    
                    try:
                        admin_msg = await context.bot.send_photo(
                            chat_id=ADMIN_USER_ID,
                            photo=photo.file_id,
                            caption=f"💰 درخواست شارژ API KEY\n\n"
                                    f"کاربر: {user_id}\n"
                                    f"مبلغ: {amount:,} تومان",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        # ذخیره message_id پیام ادمین در درخواست
                        await db.apikey_charge_requests.update_one(
                            {"id": charge_req.id},
                            {"$set": {"admin_message_id": admin_msg.message_id}}
                        )
                    except:
                        pass
                    
                    await update.message.reply_text(
                        "✅ درخواست شارژ شما ارسال شد.\n\n"
                        "لطفاً منتظر تایید ادمین بمانید."
                    )
                    context.user_data.clear()
            else:
                try:
                    amount = float(update.message.text)
                    context.user_data['api_credit_amount'] = amount
                    context.user_data['api_credit_step'] = 'receipt'
                    
                    await update.message.reply_text(
                        f"✅ مبلغ {amount:,.0f} تومان ثبت شد.\n\n"
                        f"حالا لطفاً رسید واریز را ارسال کنید:"
                    )
                except:
                    await update.message.reply_text(
                        "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                        "مثال: 50000"
                    )

        # Handle rejection reason for payment
        elif context.user_data.get('rejecting_payment_id'):
            payment_id = context.user_data['rejecting_payment_id']
            reason = update.message.text
            
            payment = await db.payment_requests.find_one({"id": payment_id})
            if payment:
                await db.payment_requests.update_one(
                    {"id": payment_id},
                    {"$set": {"status": "rejected", "rejection_reason": reason}}
                )
                
                bot_config = await db.bots.find_one({"id": payment['bot_id']})
                if bot_config and payment['bot_id'] in bot_applications:
                    bot_app = bot_applications[payment['bot_id']]
                    try:
                        # Send rejection message with return button
                        return_keyboard = [[InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]]
                        
                        await bot_app.bot.send_message(
                            chat_id=payment['user_telegram_id'],
                            text=f"❌ درخواست پرداخت شما رد شد.\n\n"
                                 f"💰 مبلغ: {payment['amount']:,} تومان\n\n"
                                 f"📝 دلیل: {reason}",
                            reply_markup=InlineKeyboardMarkup(return_keyboard)
                        )
                        
                        # Delete previous receipt message
                        if payment.get('message_id') and payment.get('chat_id'):
                            try:
                                await bot_app.bot.delete_message(
                                    chat_id=payment['chat_id'],
                                    message_id=payment['message_id']
                                )
                            except:
                                pass
                    except:
                        pass
                
                # Delete the payment request from database
                await db.payment_requests.delete_one({"id": payment_id})
                
                # Send confirmation to admin
                await update.message.reply_text(
                    "✅ درخواست پرداخت رد شد و به کاربر اطلاع داده شد."
                )
            
            context.user_data.clear()

        # Handle rejection reason for API key
        elif context.user_data.get('rejecting_apikey_id'):
            request_id = context.user_data['rejecting_apikey_id']
            reason = update.message.text
            
            req = await db.apikey_charge_requests.find_one({"id": request_id})
            if req:
                await db.apikey_charge_requests.update_one(
                    {"id": request_id},
                    {"$set": {"status": "rejected", "rejection_reason": reason}}
                )
                
                try:
                    # ارسال پیام رد به کاربر
                    await context.bot.send_message(
                        chat_id=req['user_telegram_id'],
                        text=f"❌ درخواست شارژ API KEY رد شد.\n\n"
                             f"💰 مبلغ: {req['amount']:,} تومان\n\n"
                             f"📝 دلیل رد: {reason}"
                    )
                except:
                    pass
                
                # Delete the API key charge request from database
                await db.apikey_charge_requests.delete_one({"id": request_id})
                
                await update.message.reply_text("✅ درخواست رد شد و به کاربر اطلاع داده شد.")
            
            context.user_data.clear()

        # ============ Admin Credit Management ============
        
        elif context.user_data.get('admin_credit_action'):
            action = context.user_data.get('admin_credit_action')
            target_user = context.user_data.get('admin_credit_user')
            
            if not target_user:
                # User needs to enter telegram ID first
                try:
                    target_user = int(update.message.text)
                    context.user_data['admin_credit_user'] = target_user
                    
                    # Check if user exists
                    user_data = await db.users.find_one({"telegram_id": target_user})
                    if not user_data:
                        await update.message.reply_text(
                            f"❌ کاربر با ID {target_user} یافت نشد.\n\n"
                            "لطفاً ID معتبر وارد کنید یا /start بزنید."
                        )
                        context.user_data.clear()
                        return
                    
                    await update.message.reply_text(
                        f"✅ کاربر {target_user} یافت شد.\n\n"
                        "حالا مبلغ را وارد کنید (به تومان):\n\n"
                        "مثال: 50000"
                    )
                except ValueError:
                    await update.message.reply_text(
                        "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                        "مثال: 123456789"
                    )
            else:
                # User enters amount
                try:
                    amount = float(update.message.text)
                    
                    if amount <= 0:
                        await update.message.reply_text("❌ مبلغ باید بیشتر از صفر باشد.")
                        return
                    
                    # Get or create API key
                    api_key = await db.api_keys.find_one({"user_telegram_id": target_user})
                    if not api_key:
                        # Create API key if doesn't exist
                        key = 'botmaker_' + ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
                        api_key = APIKey(key=key, user_telegram_id=target_user, balance=0.0)
                        doc = api_key.model_dump()
                        doc['created_at'] = doc['created_at'].isoformat()
                        await db.api_keys.insert_one(doc)
                    
                    # Update balance
                    if action == 'add':
                        await db.api_keys.update_one(
                            {"user_telegram_id": target_user},
                            {"$inc": {"balance": amount}}
                        )
                        action_text = "اضافه شد"
                        symbol = "+"
                    else:  # subtract
                        await db.api_keys.update_one(
                            {"user_telegram_id": target_user},
                            {"$inc": {"balance": -amount}}
                        )
                        action_text = "کم شد"
                        symbol = "-"
                    
                    # Get new balance
                    updated_api_key = await db.api_keys.find_one({"user_telegram_id": target_user})
                    new_balance = updated_api_key['balance']
                    
                    # Log transaction
                    transaction = Transaction(
                        type=f"admin_{action}",
                        amount=amount,
                        user_telegram_id=target_user,
                        api_key=updated_api_key['key'],
                        description=f"تغییر اعتبار توسط ادمین ({symbol}{amount:,.0f})"
                    )
                    trans_doc = transaction.model_dump()
                    trans_doc['timestamp'] = trans_doc['timestamp'].isoformat()
                    await db.transactions.insert_one(trans_doc)
                    
                    # Notify user
                    try:
                        await context.bot.send_message(
                            chat_id=target_user,
                            text=f"💰 اعتبار شما توسط ادمین تغییر کرد\n\n"
                                 f"{symbol}{amount:,.0f} تومان {action_text}\n"
                                 f"💰 موجودی جدید: {new_balance:,.0f} تومان"
                        )
                    except:
                        pass
                    
                    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_manage_users")]]
                    await update.message.reply_text(
                        f"✅ اعتبار کاربر {target_user} با موفقیت تغییر کرد\n\n"
                        f"{symbol}{amount:,.0f} تومان\n"
                        f"💰 موجودی جدید: {new_balance:,.0f} تومان",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data.clear()
                except ValueError:
                    await update.message.reply_text(
                        "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                        "مثال: 50000"
                    )

        # ============ Admin Search User ============
        
        elif context.user_data.get('admin_searching_user'):
            try:
                target_user_id = int(update.message.text)
                user_data = await db.users.find_one({"telegram_id": target_user_id})
                
                if not user_data:
                    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_users")]]
                    await update.message.reply_text(
                        f"❌ کاربر با ID {target_user_id} یافت نشد.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data.clear()
                    return
                
                api_key = await db.api_keys.find_one({"user_telegram_id": target_user_id})
                user_bots = await db.bots.count_documents({"owner_telegram_id": target_user_id})
                balance = api_key['balance'] if api_key else 0
                username = user_data.get('username', 'بدون نام')

                keyboard = [
                    [
                        InlineKeyboardButton("➕ افزایش اعتبار", callback_data=f"admin_add_credit_{target_user_id}"),
                        InlineKeyboardButton("➖ کاهش اعتبار", callback_data=f"admin_sub_credit_{target_user_id}")
                    ],
                    [InlineKeyboardButton("📩 ارسال پیام", callback_data=f"admin_send_msg_{target_user_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_manage_users")]
                ]

                await update.message.reply_text(
                    f"👤 جزئیات کاربر\n\n"
                    f"🆔 Telegram ID: {target_user_id}\n"
                    f"👤 نام کاربری: @{username}\n"
                    f"💰 موجودی API: {balance:,.0f} تومان\n"
                    f"🤖 تعداد ربات‌ها: {user_bots}\n"
                    f"📅 تاریخ عضویت: {user_data.get('created_at', 'نامشخص')}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.clear()
            except ValueError:
                await update.message.reply_text(
                    "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                    "مثال: 123456789"
                )

        # ============ Admin Send Message ============
        
        elif context.user_data.get('admin_sending_msg'):
            target_user_id = context.user_data.get('admin_msg_target')
            message_text = update.message.text
            
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"📩 پیام از ادمین جمیناتور:\n\n{message_text}"
                )
                
                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_manage_users")]]
                await update.message.reply_text(
                    f"✅ پیام با موفقیت به کاربر {target_user_id} ارسال شد.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_manage_users")]]
                await update.message.reply_text(
                    f"❌ خطا در ارسال پیام: {str(e)}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            context.user_data.clear()

        # ============ Admin Broadcast ============
        
        elif context.user_data.get('admin_broadcast_all'):
            message_text = update.message.text
            
            users = await db.users.find({}, {"_id": 0}).to_list(10000)
            sent_count = 0
            failed_count = 0
            
            await update.message.reply_text(
                f"📢 در حال ارسال پیام به {len(users)} کاربر...\n"
                "لطفاً صبر کنید..."
            )
            
            for user in users:
                try:
                    await context.bot.send_message(
                        chat_id=user['telegram_id'],
                        text=f"📢 پیام همگانی جمیناتور:\n\n{message_text}"
                    )
                    sent_count += 1
                    await asyncio.sleep(0.05)  # Prevent flood
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to send to {user['telegram_id']}: {e}")
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
            await update.message.reply_text(
                f"✅ ارسال پیام به پایان رسید\n\n"
                f"✅ موفق: {sent_count}\n"
                f"❌ ناموفق: {failed_count}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.clear()

        elif context.user_data.get('admin_broadcast_to_bot_owners'):
            message_text = update.message.text
            
            # Get unique bot owners
            bots = await db.bots.find({}, {"_id": 0}).to_list(10000)
            owner_ids = list(set([bot['owner_telegram_id'] for bot in bots]))
            
            sent_count = 0
            failed_count = 0
            
            await update.message.reply_text(
                f"📢 در حال ارسال پیام به {len(owner_ids)} صاحب ربات...\n"
                "لطفاً صبر کنید..."
            )
            
            for owner_id in owner_ids:
                try:
                    await context.bot.send_message(
                        chat_id=owner_id,
                        text=f"📢 پیام از جمیناتور:\n\n{message_text}"
                    )
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to send to {owner_id}: {e}")
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
            await update.message.reply_text(
                f"✅ ارسال پیام به صاحبان ربات‌ها به پایان رسید\n\n"
                f"✅ موفق: {sent_count}\n"
                f"❌ ناموفق: {failed_count}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.clear()

        elif context.user_data.get('admin_broadcast_all_bot_users'):
            message_text = update.message.text
            
            # جمع‌آوری تمام کاربران تمام ربات‌ها
            all_bots = await db.bots.find({}, {"_id": 0}).to_list(10000)
            
            if not all_bots:
                await update.message.reply_text(
                    "❌ هیچ رباتی یافت نشد.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]])
                )
                context.user_data.clear()
                return
            
            total_sent = 0
            total_failed = 0
            
            await update.message.reply_text(
                f"📢 در حال ارسال پیام به کاربران {len(all_bots)} ربات...\n"
                "لطفاً صبر کنید..."
            )
            
            # ارسال پیام به کاربران هر ربات
            for bot in all_bots:
                bot_id = bot['id']
                
                # بررسی اینکه ربات در حال اجراست
                if bot_id not in bot_applications:
                    continue
                
                bot_app = bot_applications[bot_id]
                
                # دریافت کاربران این ربات
                bot_users = await db.bot_users.find({"bot_id": bot_id}, {"_id": 0}).to_list(10000)
                
                for bot_user in bot_users:
                    try:
                        await bot_app.bot.send_message(
                            chat_id=bot_user['telegram_id'],
                            text=f"📢 پیام از جمیناتور:\n\n{message_text}"
                        )
                        total_sent += 1
                        await asyncio.sleep(0.05)  # جلوگیری از Flood
                    except Exception as e:
                        total_failed += 1
                        logger.error(f"Failed to send to {bot_user['telegram_id']} in bot {bot_id}: {e}")
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
            await update.message.reply_text(
                f"✅ ارسال پیام به تمامی کاربران ربات‌ها به پایان رسید\n\n"
                f"✅ موفق: {total_sent}\n"
                f"❌ ناموفق: {total_failed}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.clear()

        elif context.user_data.get('admin_bot_broadcast'):
            bot_id = context.user_data.get('admin_bot_broadcast')
            message_text = update.message.text
            
            # Get all users of this bot
            bot_users = await db.bot_users.find({"bot_id": bot_id}, {"_id": 0}).to_list(10000)
            bot = await db.bots.find_one({"id": bot_id})
            
            if not bot or bot_id not in bot_applications:
                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_manage_bots")]]
                await update.message.reply_text(
                    "❌ ربات یافت نشد یا فعال نیست.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.clear()
                return
            
            bot_app = bot_applications[bot_id]
            sent_count = 0
            failed_count = 0
            
            await update.message.reply_text(
                f"📢 در حال ارسال پیام به {len(bot_users)} کاربر ربات {bot['bot_name']}...\n"
                "لطفاً صبر کنید..."
            )
            
            for bot_user in bot_users:
                try:
                    await bot_app.bot.send_message(
                        chat_id=bot_user['telegram_id'],
                        text=f"📢 پیام از ادمین:\n\n{message_text}"
                    )
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to send to {bot_user['telegram_id']}: {e}")
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_manage_bots")]]
            await update.message.reply_text(
                f"✅ ارسال پیام به کاربران ربات {bot['bot_name']} به پایان رسید\n\n"
                f"✅ موفق: {sent_count}\n"
                f"❌ ناموفق: {failed_count}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.clear()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_bot_message))
    application.add_handler(MessageHandler(filters.PHOTO, main_bot_message))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    bot_applications['main_bot'] = application
    logger.info("Main bot started successfully")

# ============ User Bot Functions ============

async def start_user_bot(bot_id: str, bot_token: str, config: BotConfig):
    """Start a user-created bot"""
    try:
        application = Application.builder().token(bot_token).build()

        async def user_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id

            # Check bot's own channel (not main channel)
            is_member = await check_channel_membership(user_id, config.channel_id, context.bot)
            if not is_member:
                keyboard = [[InlineKeyboardButton("🔗 عضویت در کانال", url=f"https://t.me/{config.channel_id.replace('@', '')}")]]
                keyboard.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_bot_channel")])
                await update.message.reply_text(
                    f"سلام! 👋\n\nبرای استفاده از این ربات، لطفاً در کانال {config.channel_id} عضو شوید.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            # Create or get bot user
            bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
            is_new_user = False
            if not bot_user:
                is_new_user = True
                # مشکل 2 رفع شد - جایزه ورود
                new_user = BotUser(
                    bot_id=bot_id,
                    telegram_id=user_id,
                    username=update.effective_user.username,
                    balance=config.welcome_bonus
                )
                doc = new_user.model_dump()
                doc['created_at'] = doc['created_at'].isoformat()
                await db.bot_users.insert_one(doc)
                bot_user = new_user.model_dump()

            keyboard = [
                [
                    InlineKeyboardButton("💬 شروع گفتگو", callback_data="start_chat"),
                    InlineKeyboardButton("📷 تولید عکس", callback_data="generate_image")
                ],
                [InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")],
                [InlineKeyboardButton("📊 موجودی من", callback_data="my_balance")]
            ]

            if user_id == config.owner_telegram_id:
                keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

            # مشکل 4 رفع شد - متن بهتر خوش‌آمدگویی
            welcome_text = f"🎉 به ربات هوش مصنوعی خوش آمدید!\n\n"
            welcome_text += f"سلام {update.effective_user.first_name} عزیز! 👋\n\n"
            
            if is_new_user:
                welcome_text += f"🎁 به عنوان هدیه ورود، {config.welcome_bonus:,.0f} تومان به حساب شما اضافه شد!\n\n"
            
            welcome_text += f"🤖 **قابلیت‌های این ربات:**\n"
            welcome_text += f"✨ پاسخ به سوالات شما با هوش مصنوعی پیشرفته\n"
            welcome_text += f"💡 کمک در حل مسائل و مشکلات\n"
            welcome_text += f"📚 ارائه اطلاعات و دانش عمومی\n"
            welcome_text += f"💻 نوشتن و توضیح کد برنامه‌نویسی\n"
            welcome_text += f"✍️ کمک در نوشتن متن و محتوا\n\n"
            welcome_text += f"💰 موجودی شما: **{bot_user['balance']:,.0f}** تومان\n"
            welcome_text += f"💵 قیمت هر پیام: **{config.message_price}** تومان\n\n"
            welcome_text += f"💫 {config.bot_name}\n"
            welcome_text += f"🤖 @{config.bot_username}"

            sent_msg = await update.message.reply_text(
                welcome_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        async def user_bot_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            user_id = update.effective_user.id

            if query.data == "check_bot_channel":
                is_member = await check_channel_membership(user_id, config.channel_id, context.bot)
                if is_member:
                    bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                    is_new_user = False
                    if not bot_user:
                        is_new_user = True
                        new_user = BotUser(
                            bot_id=bot_id,
                            telegram_id=user_id,
                            username=update.effective_user.username,
                            balance=config.welcome_bonus
                        )
                        doc = new_user.model_dump()
                        doc['created_at'] = doc['created_at'].isoformat()
                        await db.bot_users.insert_one(doc)
                        bot_user = new_user.model_dump()

                    keyboard = [
                        [
                            InlineKeyboardButton("💬 شروع گفتگو", callback_data="start_chat"),
                            InlineKeyboardButton("📷 تولید عکس", callback_data="generate_image")
                        ],
                        [InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")],
                        [InlineKeyboardButton("📊 موجودی من", callback_data="my_balance")]
                    ]

                    if user_id == config.owner_telegram_id:
                        keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

                    welcome_text = f"🎉 به ربات هوش مصنوعی خوش آمدید!\n\n"
                    welcome_text += f"سلام! 👋\n\n"
                    
                    if is_new_user:
                        welcome_text += f"🎁 به عنوان هدیه ورود، {config.welcome_bonus:,.0f} تومان به حساب شما اضافه شد!\n\n"
                    
                    welcome_text += f"🤖 **قابلیت‌های این ربات:**\n"
                    welcome_text += f"✨ پاسخ به سوالات با هوش مصنوعی\n"
                    welcome_text += f"💡 کمک در حل مسائل\n"
                    welcome_text += f"📚 اطلاعات و دانش عمومی\n"
                    welcome_text += f"💻 نوشتن و توضیح کد\n\n"
                    welcome_text += f"💰 موجودی شما: **{bot_user['balance']:,.0f}** تومان\n"
                    welcome_text += f"💵 قیمت هر پیام: **{config.message_price}** تومان\n\n"
                    welcome_text += f"💫 {config.bot_name}\n"
                    welcome_text += f"🤖 @{config.bot_username}"

                    await query.edit_message_text(
                        welcome_text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await query.answer("⚠️ لطفاً ابتدا در کانال ربات عضو شوید.", show_alert=True)
            
            elif query.data == "start_chat":
                bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                keyboard = [
                    [InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")],
                    [InlineKeyboardButton("📊 موجودی من", callback_data="my_balance")]
                ]
                
                if user_id == config.owner_telegram_id:
                    keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])
                
                await query.edit_message_text(
                    f"✨ گفتگو آغاز شد!\n\n"
                    f"💰 موجودی شما: **{bot_user['balance']:,.0f}** تومان\n"
                    f"💵 قیمت هر پیام: **{config.message_price}** تومان\n\n"
                    f"🤖 سوال خود را بپرسید...\n\n"
                    f"💫 {config.bot_name}\n"
                    f"🤖 @{config.bot_username}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif query.data == "buy_credit":
                await query.edit_message_text(
                    f"💰 خرید شارژ\n\n"
                    f"💳 شماره کارت: `{config.card_number}`\n"
                    f"👤 به نام: {config.card_holder}\n\n"
                    f"لطفاً مبلغ مورد نظر را به شماره کارت بالا واریز کنید و سپس:\n"
                    f"1️⃣ مبلغ واریزی را ارسال کنید (فقط عدد، به تومان)\n\n"
                    f"مثال: 50000",
                    parse_mode='Markdown'
                )
                context.user_data['buying_credit'] = True

            elif query.data == "my_balance":
                bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]]
                await query.edit_message_text(
                    f"📊 اطلاعات حساب شما:\n\n"
                    f"💰 موجودی: {bot_user['balance']:,.0f} تومان\n"
                    f"💵 قیمت هر پیام: {config.message_price} تومان\n"
                    f"📊 تعداد پیام‌های قابل ارسال: {int(bot_user['balance'] / config.message_price) if config.message_price > 0 else 0}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif query.data == "admin_panel":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                # Count pending payment requests for this bot
                pending_bot_payments = await db.payment_requests.count_documents({
                    "bot_id": bot_id,
                    "status": "pending"
                })

                keyboard = [
                    [InlineKeyboardButton(f"💰 درخواست‌های پرداخت ({pending_bot_payments})", callback_data="bot_payment_requests")],
                    [InlineKeyboardButton("💵 تنظیم قیمت پیام", callback_data="set_message_price")],
                    [InlineKeyboardButton("🎁 تنظیم جایزه ورود", callback_data="set_welcome_bonus")],
                    [InlineKeyboardButton("⚙️ تنظیمات پرداخت", callback_data="payment_settings")],
                    [InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],
                    [InlineKeyboardButton("📢 ارسال پیام به کاربران", callback_data="admin_broadcast")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
                ]

                await query.edit_message_text(
                    "👨‍💼 پنل مدیریت ربات\n\n"
                    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif query.data == "bot_payment_requests":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                # Get pending payment requests for this bot
                payments = await db.payment_requests.find({
                    "bot_id": bot_id,
                    "status": "pending"
                }).to_list(10)

                if not payments:
                    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
                    await query.edit_message_text(
                        "💰 درخواست‌های پرداخت\n\n"
                        "هیچ درخواست پرداخت در انتظاری وجود ندارد.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    text = "💰 درخواست‌های پرداخت در انتظار:\n\n"
                    keyboard = []

                    for payment in payments[:5]:
                        user = await db.bot_users.find_one({
                            "bot_id": bot_id,
                            "telegram_id": payment['user_telegram_id']
                        })
                        username = user.get('username', 'نامشخص') if user else 'نامشخص'
                        text += f"• {payment['amount']:,} تومان - @{username if username else payment['user_telegram_id']}\n"
                        keyboard.append([
                            InlineKeyboardButton(f"✅ تایید {payment['amount']:,}", callback_data=f"approve_payment_{payment['id']}"),
                            InlineKeyboardButton("❌ رد", callback_data=f"reject_payment_{payment['id']}")
                        ])

                    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")])

                    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

            elif query.data == "set_message_price":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                context.user_data['setting_message_price'] = True
                await query.edit_message_text(
                    f"💰 تنظیم قیمت پیام\n\n"
                    f"💵 قیمت فعلی: {config.message_price} تومان\n\n"
                    f"لطفاً قیمت جدید را وارد کنید (از 0 تا 20 تومان):"
                )

            elif query.data == "set_welcome_bonus":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                context.user_data['setting_welcome_bonus'] = True
                await query.edit_message_text(
                    f"🎁 تنظیم جایزه ورود\n\n"
                    f"💰 جایزه فعلی: {config.welcome_bonus} تومان\n\n"
                    f"لطفاً مبلغ جدید جایزه ورود را وارد کنید (از 0 تا 10000 تومان):"
                )

            elif query.data == "payment_settings":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                bot_config = await db.bots.find_one({"id": bot_id})
                keyboard = [
                    [InlineKeyboardButton("💳 تنظیم شماره کارت", callback_data="set_card_number")],
                    [InlineKeyboardButton("👤 تنظیم نام صاحب کارت", callback_data="set_card_holder")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
                ]

                await query.edit_message_text(
                    "⚙️ تنظیمات پرداخت\n\n"
                    f"💳 شماره کارت: {bot_config.get('card_number', '6219861865900301')}\n"
                    f"👤 به نام: {bot_config.get('card_holder', 'محمد وظیفه دان')}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif query.data == "set_card_number":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                context.user_data['setting_card_number'] = True
                await query.edit_message_text(
                    "💳 تنظیم شماره کارت\n\n"
                    "لطفاً شماره کارت جدید را وارد کنید:"
                )

            elif query.data == "set_card_holder":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                context.user_data['setting_card_holder'] = True
                await query.edit_message_text(
                    "👤 تنظیم نام صاحب کارت\n\n"
                    "لطفاً نام صاحب کارت را وارد کنید:"
                )

            elif query.data == "admin_stats":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                total_users = await db.bot_users.count_documents({"bot_id": bot_id})
                total_messages = await db.messages.count_documents({"bot_id": bot_id})

                api_key_doc = await db.api_keys.find_one({"key": config.api_key})
                api_balance = api_key_doc['balance'] if api_key_doc else 0

                keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]

                await query.edit_message_text(
                    f"📊 آمار کلی ربات\n\n"
                    f"👥 تعداد کاربران: {total_users:,}\n"
                    f"💬 تعداد پیام‌ها: {total_messages:,}\n"
                    f"💰 موجودی API KEY: {api_balance:,.0f} تومان\n"
                    f"💵 قیمت هر پیام: {config.message_price} تومان\n"
                    f"🔒 قفل کانال اصلی: {'فعال' if config.main_channel_locked else 'غیرفعال'}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif query.data == "admin_broadcast":
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ادمین ندارید.", show_alert=True)
                    return

                context.user_data['broadcasting'] = True
                await query.edit_message_text(
                    "📢 ارسال پیام به کاربران\n\n"
                    "لطفاً پیام خود را وارد کنید:"
                )

            elif query.data == "generate_image":
                bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                await query.edit_message_text(
                    f"📷 تولید عکس با هوش مصنوعی\n\n"
                    f"💰 موجودی شما: **{bot_user['balance']:,.0f}** تومان\n"
                    f"💵 قیمت تولید عکس: **{IMAGE_GENERATION_PRICE_USER}** تومان\n\n"
                    f"لطفاً توضیح دهید چه عکسی می‌خواهید؟\n\n"
                    f"مثال: یک گربه زیبا در باغ با گل‌های رنگارنگ",
                    parse_mode='Markdown'
                )
                context.user_data['generating_image'] = True

            elif query.data.startswith("confirm_image_"):
                # Extract the prompt from callback data
                prompt = context.user_data.get('image_prompt', '')
                
                if query.data == "confirm_image_yes":
                    bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                    
                    # Check if user has enough balance
                    if bot_user['balance'] < IMAGE_GENERATION_PRICE_USER:
                        keyboard = [[InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")]]
                        await query.edit_message_text(
                            f"⚠️ موجودی شما کافی نیست.\n\n"
                            f"موجودی فعلی: {bot_user['balance']:,.0f} تومان\n"
                            f"قیمت تولید عکس: {IMAGE_GENERATION_PRICE_USER} تومان",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        return
                    
                    await query.edit_message_text("🎨 در حال تولید عکس...\nلطفاً صبر کنید...")
                    
                    try:
                        # Translate prompt to English using Groq
                        groq_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)
                        translation_response = await asyncio.wait_for(
                            groq_client.chat.completions.create(
                                model=GROQ_MODEL,
                                messages=[
                                    {"role": "system", "content": "You are a translator. Translate the following text to English for image generation. Only respond with the English translation, nothing else. Make it descriptive and suitable for AI image generation."},
                                    {"role": "user", "content": prompt}
                                ]
                            ),
                            timeout=30.0
                        )
                        english_prompt = translation_response.choices[0].message.content.strip()
                        
                        # Generate image URL from pollinations.ai
                        import urllib.parse
                        import httpx
                        from io import BytesIO
                        
                        encoded_prompt = urllib.parse.quote(english_prompt)
                        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
                        
                        # Download the image first
                        async with httpx.AsyncClient(timeout=60.0) as client:
                            image_response = await asyncio.wait_for(
                                client.get(image_url),
                                timeout=60.0
                            )
                            image_response.raise_for_status()
                            image_bytes = BytesIO(image_response.content)
                            image_bytes.name = 'generated_image.jpg'
                        
                        # Send the downloaded image
                        await asyncio.wait_for(
                            context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=image_bytes,
                                caption=f"✨ عکس تولید شد!\n\n📝 توضیحات: {prompt}\n\n💰 {IMAGE_GENERATION_PRICE_USER} تومان از موجودی شما کسر شد.\n\n━━━━━━━━━━━━━━\n💫 {config.bot_name}\n🤖 @{config.bot_username}",
                                read_timeout=60.0,
                                write_timeout=60.0,
                                connect_timeout=60.0,
                                pool_timeout=60.0
                            ),
                            timeout=90.0
                        )
                        
                        # Deduct balance from user
                        await db.bot_users.update_one(
                            {"bot_id": bot_id, "telegram_id": user_id},
                            {"$inc": {"balance": -IMAGE_GENERATION_PRICE_USER}}
                        )
                        
                        # Deduct 50 تومان from API key owner (هزینه تولید عکس)
                        await db.api_keys.update_one(
                            {"key": config.api_key},
                            {"$inc": {"balance": -IMAGE_GENERATION_PRICE_API}}
                        )
                        
                        # Log transaction
                        transaction = Transaction(
                            type="image_generation",
                            amount=IMAGE_GENERATION_PRICE_USER,
                            user_telegram_id=user_id,
                            bot_id=bot_id,
                            api_key=config.api_key,
                            description=f"تولید عکس: {prompt[:50]}"
                        )
                        trans_doc = transaction.model_dump()
                        trans_doc['timestamp'] = trans_doc['timestamp'].isoformat()
                        await db.transactions.insert_one(trans_doc)
                        
                    except asyncio.TimeoutError:
                        logger.error("Image generation timeout")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="❌ متأسفانه تولید عکس بیش از حد طول کشید.\n\n"
                                 "لطفاً دوباره تلاش کنید یا متن کوتاه‌تری بنویسید."
                        )
                    except Exception as e:
                        logger.error(f"Error generating image: {e}")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=f"❌ خطا در تولید عکس: {str(e)}\n\n"
                                 "لطفاً دوباره تلاش کنید."
                        )
                    
                    context.user_data.clear()
                    
                elif query.data == "confirm_image_no":
                    await query.edit_message_text(
                        "❌ درخواست تولید عکس لغو شد.\n\n"
                        "می‌توانید دوباره امتحان کنید."
                    )
                    context.user_data.clear()

            elif query.data.startswith("approve_payment_"):
                # Only bot owner can approve payments
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ندارید.", show_alert=True)
                    return

                payment_id = query.data.replace("approve_payment_", "")
                payment = await db.payment_requests.find_one({"id": payment_id})
                
                if not payment:
                    await query.answer("❌ درخواست پرداخت یافت نشد.", show_alert=True)
                    return

                # Update balance
                await db.bot_users.update_one(
                    {"bot_id": bot_id, "telegram_id": payment['user_telegram_id']},
                    {"$inc": {"balance": payment['amount']}}
                )

                # Update payment status
                await db.payment_requests.update_one(
                    {"id": payment_id},
                    {"$set": {"status": "approved"}}
                )

                # Send message to user
                try:
                    await context.bot.send_message(
                        chat_id=payment['user_telegram_id'],
                        text=f"✅ پرداخت شما با موفقیت تایید شد!\n\n"
                             f"💰 مبلغ: {payment['amount']:,} تومان\n"
                             f"✨ موجودی به حساب شما اضافه شد.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
                        ]])
                    )
                    
                    # Delete previous receipt message
                    if payment.get('message_id') and payment.get('chat_id'):
                        try:
                            await context.bot.delete_message(
                                chat_id=payment['chat_id'],
                                message_id=payment['message_id']
                            )
                        except:
                            pass
                except Exception as e:
                    logger.error(f"Error sending approval message: {e}")

                # Remove buttons from admin message (don't delete the photo)
                await query.answer("✅ پرداخت تایید شد.", show_alert=True)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except:
                    pass

            elif query.data.startswith("reject_payment_"):
                # Only bot owner can reject payments
                if user_id != config.owner_telegram_id:
                    await query.answer("⚠️ شما دسترسی ندارید.", show_alert=True)
                    return

                payment_id = query.data.replace("reject_payment_", "")
                payment = await db.payment_requests.find_one({"id": payment_id})
                
                if not payment:
                    await query.answer("❌ درخواست پرداخت یافت نشد.", show_alert=True)
                    return

                context.user_data['rejecting_payment_id'] = payment_id
                context.user_data['rejecting_payment_user_id'] = payment['user_telegram_id']
                context.user_data['rejecting_payment_amount'] = payment['amount']
                context.user_data['rejecting_payment_message_id'] = payment.get('message_id')
                context.user_data['rejecting_payment_chat_id'] = payment.get('chat_id')

                # Delete the message with buttons
                try:
                    await query.message.delete()
                except:
                    pass
                
                # Send new message asking for reason
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ رد کردن درخواست پرداخت\n\n"
                         "لطفاً دلیل رد کردن را وارد کنید:"
                )

            elif query.data == "back_to_main":
                bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                keyboard = [
                    [
                        InlineKeyboardButton("💬 شروع گفتگو", callback_data="start_chat"),
                        InlineKeyboardButton("📷 تولید عکس", callback_data="generate_image")
                    ],
                    [InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")],
                    [InlineKeyboardButton("📊 موجودی من", callback_data="my_balance")]
                ]

                if user_id == config.owner_telegram_id:
                    keyboard.append([InlineKeyboardButton("👨‍💼 پنل مدیریت", callback_data="admin_panel")])

                await query.edit_message_text(
                    f"🏠 منوی اصلی\n\n"
                    f"💰 موجودی شما: **{bot_user['balance']:,.0f}** تومان\n"
                    f"💵 قیمت هر پیام: **{config.message_price}** تومان\n\n"
                    f"💫 {config.bot_name}\n"
                    f"🤖 @{config.bot_username}",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        async def user_bot_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id

            # Add heart reaction to user message
            try:
                await update.message.set_reaction(ReactionEmoji.RED_HEART)
            except:
                pass

            # Handle photo receipt
            if update.message.photo and context.user_data.get('buying_credit'):
                if context.user_data.get('credit_step') == 'receipt':
                    photo = update.message.photo[-1]
                    amount = context.user_data.get('credit_amount', 0)
                    
                    payment_req = PaymentRequest(
                        bot_id=bot_id,
                        user_telegram_id=user_id,
                        amount=amount,
                        receipt_photo=photo.file_id,
                        message_id=update.message.message_id,
                        chat_id=update.message.chat_id,
                        status="pending"
                    )
                    doc = payment_req.model_dump()
                    doc['created_at'] = doc['created_at'].isoformat()
                    await db.payment_requests.insert_one(doc)
                    
                    bot_config = await db.bots.find_one({"id": bot_id})
                    owner_id = bot_config['owner_telegram_id']
                    
                    keyboard = [
                        [InlineKeyboardButton("✅ تایید", callback_data=f"approve_payment_{payment_req.id}")],
                        [InlineKeyboardButton("❌ رد کردن", callback_data=f"reject_payment_{payment_req.id}")]
                    ]
                    
                    # ارسال رسید به صاحب ربات (owner) از طریق همین ربات
                    try:
                        await context.bot.send_message(
                            chat_id=owner_id,
                            text=f"🔔 **درخواست پرداخت جدید!**\n\n"
                                 f"یک رسید از طرف کاربر {user_id} دریافت شد.\n"
                                 f"مبلغ: **{amount:,}** تومان\n\n"
                                 f"لطفاً رسید را بررسی کنید.",
                            parse_mode='Markdown'
                        )
                        
                        await context.bot.send_photo(
                            chat_id=owner_id,
                            photo=photo.file_id,
                            caption=f"💰 رسید درخواست پرداخت\n\n"
                                    f"ربات: {bot_config['bot_name']}\n"
                                    f"کاربر: {user_id}\n"
                                    f"مبلغ: {amount:,} تومان",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    except Exception as e:
                        logger.error(f"Error sending payment receipt: {e}")
                    
                    await update.message.reply_text(
                        "✅ درخواست پرداخت شما ارسال شد.\n\n"
                        "لطفاً منتظر تایید ادمین باشید."
                    )
                    context.user_data.clear()
                return

            # Handle rejection reason
            if context.user_data.get('rejecting_payment_id'):
                payment_id = context.user_data['rejecting_payment_id']
                reason = update.message.text
                target_user_id = context.user_data.get('rejecting_payment_user_id')
                amount = context.user_data.get('rejecting_payment_amount', 0)
                message_id = context.user_data.get('rejecting_payment_message_id')
                chat_id = context.user_data.get('rejecting_payment_chat_id')
                
                # Update payment status
                await db.payment_requests.update_one(
                    {"id": payment_id},
                    {"$set": {"status": "rejected", "rejection_reason": reason}}
                )
                
                # Send rejection message to user
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"❌ درخواست پرداخت شما رد شد.\n\n"
                             f"💰 مبلغ: {amount:,} تومان\n\n"
                             f"📝 دلیل: {reason}",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
                        ]])
                    )
                    
                    # Delete previous receipt message
                    if message_id and chat_id:
                        try:
                            await context.bot.delete_message(
                                chat_id=chat_id,
                                message_id=message_id
                            )
                        except:
                            pass
                except Exception as e:
                    logger.error(f"Error sending rejection message: {e}")
                
                await update.message.reply_text(
                    "✅ درخواست پرداخت رد شد و پیام برای کاربر ارسال شد.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")
                    ]])
                )
                context.user_data.clear()
                return

            # Handle buying credit
            if context.user_data.get('buying_credit'):
                try:
                    amount = float(update.message.text)
                    context.user_data['credit_amount'] = amount
                    context.user_data['credit_step'] = 'receipt'
                    
                    await update.message.reply_text(
                        f"✅ مبلغ {amount:,.0f} تومان ثبت شد.\n\n"
                        f"حالا لطفاً رسید واریز را ارسال کنید:"
                    )
                except:
                    await update.message.reply_text(
                        "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                        "مثال: 50000"
                    )
                return

            # Handle setting message price
            if context.user_data.get('setting_message_price'):
                try:
                    price = float(update.message.text)
                    if price < 0 or price > 20:
                        await update.message.reply_text(
                            "❌ قیمت باید بین 0 تا 20 تومان باشد.\n\n"
                            "لطفاً دوباره وارد کنید:"
                        )
                        return

                    await db.bots.update_one({"id": bot_id}, {"$set": {"message_price": price}})
                    config.message_price = price

                    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                    await update.message.reply_text(
                        f"✅ قیمت هر پیام به {price} تومان تغییر یافت.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data.clear()
                except ValueError:
                    await update.message.reply_text(
                        "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                        "قیمت جدید (0 تا 20 تومان):"
                    )
                return

            # Handle setting welcome bonus
            if context.user_data.get('setting_welcome_bonus'):
                try:
                    bonus = float(update.message.text)
                    if bonus < 0 or bonus > 10000:
                        await update.message.reply_text(
                            "❌ جایزه باید بین 0 تا 10000 تومان باشد.\n\n"
                            "لطفاً دوباره وارد کنید:"
                        )
                        return

                    await db.bots.update_one({"id": bot_id}, {"$set": {"welcome_bonus": bonus}})
                    config.welcome_bonus = bonus

                    keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                    await update.message.reply_text(
                        f"✅ جایزه ورود به {bonus} تومان تغییر یافت.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data.clear()
                except ValueError:
                    await update.message.reply_text(
                        "❌ لطفاً یک عدد معتبر وارد کنید.\n\n"
                        "جایزه جدید (0 تا 10000 تومان):"
                    )
                return

            # Handle setting card number
            if context.user_data.get('setting_card_number'):
                card_number = update.message.text.strip()
                await db.bots.update_one({"id": bot_id}, {"$set": {"card_number": card_number}})
                config.card_number = card_number

                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                await update.message.reply_text(
                    f"✅ شماره کارت به `{card_number}` تغییر یافت.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.clear()
                return

            # Handle setting card holder
            if context.user_data.get('setting_card_holder'):
                card_holder = update.message.text.strip()
                await db.bots.update_one({"id": bot_id}, {"$set": {"card_holder": card_holder}})
                config.card_holder = card_holder

                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                await update.message.reply_text(
                    f"✅ نام صاحب کارت به {card_holder} تغییر یافت.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.clear()
                return

            # Handle image generation request - مستقیماً تولید میشه بدون تأیید
            if context.user_data.get('generating_image'):
                prompt = update.message.text
                context.user_data['generating_image'] = False
                
                # Check balance
                bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
                if not bot_user or bot_user['balance'] < IMAGE_GENERATION_PRICE_USER:
                    keyboard = [[InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")]]
                    await update.message.reply_text(
                        f"⚠️ موجودی شما برای تولید عکس کافی نیست.\n\n"
                        f"موجودی فعلی: {bot_user['balance'] if bot_user else 0:,.0f} تومان\n"
                        f"قیمت تولید عکس: {IMAGE_GENERATION_PRICE_USER} تومان",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data.clear()
                    return
                
                # Generate image directly
                status_msg = await update.message.reply_text("🎨 در حال تولید عکس...\nلطفاً صبر کنید...")
                
                try:
                    # Use Groq to enhance prompt (translate Persian to English)
                    groq_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)
                    enhance_response = await asyncio.wait_for(
                        groq_client.chat.completions.create(
                            model="llama-3.3-70b-versatile",
                            messages=[
                                {"role": "system", "content": "You are a helpful assistant that enhances image generation prompts. Convert Persian/Arabic text to English if needed and make it detailed for AI image generation. Return ONLY the enhanced English prompt, nothing else."},
                                {"role": "user", "content": f"Enhance this prompt for AI image generation: {prompt}"}
                            ]
                        ),
                        timeout=15
                    )
                    enhanced_prompt = enhance_response.choices[0].message.content.strip()
                    
                    # Generate image using Pollinations AI (free service)
                    import httpx
                    encoded_prompt = urllib.parse.quote(enhanced_prompt)
                    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&model=flux"
                    
                    # Download and verify image
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.get(image_url)
                        if response.status_code != 200:
                            raise Exception("Failed to generate image")
                    
                    # Send image
                    await status_msg.delete()
                    await context.bot.send_photo(
                        chat_id=update.message.chat_id,
                        photo=image_url,
                        caption=f"✨ عکس تولید شد!\n\n📝 توضیحات: {prompt}\n\n💰 {IMAGE_GENERATION_PRICE_USER} تومان از موجودی شما کسر شد.\n\n━━━━━━━━━━━━━━\n💫 {config.bot_name}\n🤖 @{config.bot_username}",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔄 تولید دوباره", callback_data="generate_image"),
                            InlineKeyboardButton("💬 چت با ربات", callback_data="back_to_main")
                        ]])
                    )
                    
                    # Deduct from user
                    await db.bot_users.update_one(
                        {"bot_id": bot_id, "telegram_id": user_id},
                        {"$inc": {"balance": -IMAGE_GENERATION_PRICE_USER}}
                    )
                    
                    # Deduct 50 تومان from API key owner (هزینه تولید عکس برای سازنده)
                    await db.api_keys.update_one(
                        {"key": config.api_key},
                        {"$inc": {"balance": -IMAGE_GENERATION_PRICE_API}}
                    )
                    
                    # Log transaction
                    transaction = Transaction(
                        type="image_generation",
                        amount=IMAGE_GENERATION_PRICE_USER,
                        user_telegram_id=user_id,
                        bot_id=bot_id,
                        api_key=config.api_key,
                        description=f"تولید عکس: {prompt[:50]}"
                    )
                    trans_doc = transaction.model_dump()
                    trans_doc['timestamp'] = trans_doc['timestamp'].isoformat()
                    await db.transactions.insert_one(trans_doc)
                    
                except asyncio.TimeoutError:
                    await status_msg.edit_text(
                        "❌ متأسفانه تولید عکس بیش از حد طول کشید.\n\n"
                        "لطفاً دوباره تلاش کنید.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تلاش مجدد", callback_data="generate_image")]])
                    )
                except Exception as e:
                    logger.error(f"Error generating image: {e}")
                    await status_msg.edit_text(
                        f"❌ خطا در تولید عکس: {str(e)}\n\n"
                        f"لطفاً دوباره تلاش کنید.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تلاش مجدد", callback_data="generate_image")]])
                    )
                
                context.user_data.clear()
                return

            # Handle broadcast message - هدف 5 رفع شد
            if context.user_data.get('broadcasting'):
                message_text = update.message.text

                bot_users = await db.bot_users.find({"bot_id": bot_id}).to_list(1000)

                success_count = 0
                fail_count = 0

                for bot_user in bot_users:
                    if bot_user['telegram_id'] == user_id:  # Skip owner
                        continue
                    try:
                        await context.bot.send_message(
                            chat_id=bot_user['telegram_id'],
                            text=f"💫 {config.bot_name}\n🤖 @{config.bot_username}\n\n📢 پیام از ادمین:\n\n{message_text}"
                        )
                        success_count += 1
                        await asyncio.sleep(0.1)
                    except:
                        fail_count += 1

                keyboard = [[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")]]
                await update.message.reply_text(
                    f"✅ پیام ارسال شد!\n\n"
                    f"✅ موفق: {success_count}\n"
                    f"❌ ناموفق: {fail_count}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.clear()
                return

            # Handle normal chat (حذف شد پیام تأیید عکس - فقط از دکمه تولید عکس میشه)
            bot_user = await db.bot_users.find_one({"bot_id": bot_id, "telegram_id": user_id})
            if not bot_user or bot_user['balance'] < config.message_price:
                keyboard = [[InlineKeyboardButton("💰 خرید شارژ", callback_data="buy_credit")]]
                await update.message.reply_text(
                    "⚠️ موجودی شما کافی نیست.\n\n"
                    f"موجودی فعلی: {bot_user['balance'] if bot_user else 0:,.0f} تومان\n"
                    f"قیمت هر پیام: {config.message_price} تومان",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            # هدف 1 رفع شد - Show thinking and get AI response
            thinking_msg = await update.message.reply_text("🤔 درحال فکر کردن...")

            # Get conversation history
            messages_history = await db.messages.find(
                {"bot_id": bot_id, "user_telegram_id": user_id}
            ).sort("timestamp", -1).limit(50).to_list(50)
            messages_history.reverse()

            conversation = [{"role": msg['role'], "content": msg['content']} for msg in messages_history]
            conversation.append({"role": "user", "content": update.message.text})

            try:
                groq_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)
                response = await groq_client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=conversation,
                    stream=False
                )

                ai_response = response.choices[0].message.content

                # مشکل 7 رفع شد - بهبود قالب‌بندی پاسخ AI
                # Process AI response for better formatting
                formatted_response = ai_response
                
                # Format code blocks properly
                import re
                code_pattern = r'```(\w+)?\n(.*?)```'
                formatted_response = re.sub(
                    code_pattern,
                    lambda m: f"```{m.group(1) or ''}\n{m.group(2)}```",
                    formatted_response,
                    flags=re.DOTALL
                )

                # Edit message with response gradually
                words = formatted_response.split()
                displayed_text = ""
                
                for i, word in enumerate(words):
                    displayed_text += word + " "
                    if i % 15 == 0 and i > 0:
                        try:
                            await thinking_msg.edit_text(
                                displayed_text.strip(),
                                parse_mode='Markdown'
                            )
                            await asyncio.sleep(0.05)
                        except:
                            try:
                                # Fallback without markdown if parsing fails
                                await thinking_msg.edit_text(displayed_text.strip())
                            except:
                                pass

                # Final message with bot info at the bottom
                final_text = f"{formatted_response}\n\n━━━━━━━━━━━━━━\n💫 {config.bot_name}\n🤖 @{config.bot_username}"
                
                try:
                    await thinking_msg.edit_text(final_text, parse_mode='Markdown')
                except:
                    # Fallback without markdown
                    await thinking_msg.edit_text(final_text)

                # Deduct balance from user
                await db.bot_users.update_one(
                    {"bot_id": bot_id, "telegram_id": user_id},
                    {"$inc": {"balance": -config.message_price}}
                )
                
                # Deduct 5 تومان from API key owner (هزینه استفاده از API برای سازنده)
                await db.api_keys.update_one(
                    {"key": config.api_key},
                    {"$inc": {"balance": -5.0}}
                )
                
                # Log transaction
                transaction = Transaction(
                    type="message",
                    amount=config.message_price,
                    user_telegram_id=user_id,
                    bot_id=bot_id,
                    api_key=config.api_key,
                    description=f"پیام چت: {update.message.text[:30]}..."
                )
                trans_doc = transaction.model_dump()
                trans_doc['timestamp'] = trans_doc['timestamp'].isoformat()
                await db.transactions.insert_one(trans_doc)

                # Save messages
                user_msg = Message(bot_id=bot_id, user_telegram_id=user_id, role="user", content=update.message.text)
                assistant_msg = Message(bot_id=bot_id, user_telegram_id=user_id, role="assistant", content=ai_response)

                user_doc = user_msg.model_dump()
                user_doc['timestamp'] = user_doc['timestamp'].isoformat()
                assistant_doc = assistant_msg.model_dump()
                assistant_doc['timestamp'] = assistant_doc['timestamp'].isoformat()

                await db.messages.insert_one(user_doc)
                await db.messages.insert_one(assistant_doc)

                # حذف پیام‌های قدیمی - بعد از 55 پیام
                total_messages = await db.messages.count_documents({"bot_id": bot_id, "user_telegram_id": user_id})
                if total_messages > 55:
                    messages_to_delete = await db.messages.find(
                        {"bot_id": bot_id, "user_telegram_id": user_id}
                    ).sort("timestamp", 1).limit(total_messages - 55).to_list(total_messages - 55)
                    
                    for msg in messages_to_delete:
                        await db.messages.delete_one({"_id": msg['_id']})

            except Exception as e:
                await thinking_msg.edit_text(f"❌ خطا در پردازش: {str(e)}")
                logger.error(f"Error in AI response: {e}")

        application.add_handler(CommandHandler("start", user_bot_start))
        application.add_handler(CallbackQueryHandler(user_bot_button))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_bot_message))
        application.add_handler(MessageHandler(filters.PHOTO, user_bot_message))

        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        bot_applications[bot_id] = application
        logger.info(f"User bot {bot_id} started successfully")
    except Exception as e:
        logger.error(f"Error starting user bot {bot_id}: {e}")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Start main bot and existing user bots on startup"""
    asyncio.create_task(start_main_bot())

    bots = await db.bots.find({"status": "running"}).to_list(1000)
    for bot in bots:
        bot_config = BotConfig(**bot)
        asyncio.create_task(start_user_bot(bot['id'], bot['bot_token'], bot_config))

    logger.info(f"Started {len(bots)} existing bots")

@app.on_event("shutdown")
async def shutdown_event():
    """Stop all bots on shutdown"""
    for bot_id, application in bot_applications.items():
        try:
            await application.stop()
            await application.shutdown()
        except:
            pass
    client.close()
    logger.info("All bots stopped")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

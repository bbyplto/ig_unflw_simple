import asyncio
import logging
import random
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import instaloader
import requests
from typing import List, Dict, Optional
import os
from dataclasses import dataclass

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class InstagramUser:
    username: str
    full_name: str
    followers_count: int
    profile_pic_url: str
    is_verified: bool
    is_private: bool

class InstagramAnalyzer:
    def __init__(self):
        self.loader = instaloader.Instaloader()
        self.last_request_time = 0
        self.request_delay = random.uniform(5, 10)  # Увеличенные задержки для безопасности
        
        # Настройка для избежания блокировок
        self.loader.context.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    
    async def wait_for_rate_limit(self):
        """Соблюдение лимитов запросов с увеличенными задержками"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.request_delay:
            sleep_time = self.request_delay - time_since_last_request
            logger.info(f"Ожидание {sleep_time:.2f} секунд для соблюдения лимитов...")
            await asyncio.sleep(sleep_time)
        
        self.last_request_time = time.time()
        # Рандомизируем следующую задержку (5-15 секунд)
        self.request_delay = random.uniform(5, 15)
    
    async def get_profile_info(self, username: str) -> Optional[InstagramUser]:
        """Получение информации о профиле с задержками"""
        try:
            await self.wait_for_rate_limit()
            
            username = username.replace('@', '').replace('https://instagram.com/', '').replace('https://www.instagram.com/', '').strip('/')
            
            profile = instaloader.Profile.from_username(self.loader.context, username)
            
            return InstagramUser(
                username=profile.username,
                full_name=profile.full_name,
                followers_count=profile.followers,
                profile_pic_url=profile.profile_pic_url,
                is_verified=profile.is_verified,
                is_private=profile.is_private
            )
        except Exception as e:
            logger.error(f"Ошибка получения профиля {username}: {e}")
            return None
    
    async def get_followers_and_following(self, username: str, max_count: int = 500) -> Dict[str, List[InstagramUser]]:
        """Получение подписчиков и подписок с ограничениями"""
        try:
            username = username.replace('@', '').strip('/')
            
            await self.wait_for_rate_limit()
            profile = instaloader.Profile.from_username(self.loader.context, username)
            
            if profile.is_private:
                return {"error": "Профиль закрытый"}
            
            logger.info(f"Начинаю анализ профиля @{profile.username}")
            logger.info(f"Подписчиков: {profile.followers}, Подписок: {profile.followees}")
            
            followers = []
            following = []
            
            # Получаем подписчиков с ограничением и большими задержками
            logger.info("Получаю список подписчиков...")
            count = 0
            try:
                for follower in profile.get_followers():
                    if count >= max_count:
                        break
                        
                    await self.wait_for_rate_limit()  # Задержка между каждым пользователем
                    
                    user_info = InstagramUser(
                        username=follower.username,
                        full_name=follower.full_name,
                        followers_count=follower.followers,
                        profile_pic_url=follower.profile_pic_url,
                        is_verified=follower.is_verified,
                        is_private=follower.is_private
                    )
                    followers.append(user_info)
                    count += 1
                    
                    if count % 10 == 0:
                        logger.info(f"Получено подписчиков: {count}")
                        # Дополнительная задержка каждые 10 пользователей
                        await asyncio.sleep(random.uniform(10, 20))
                        
            except Exception as e:
                logger.error(f"Ошибка получения подписчиков: {e}")
                if not followers:
                    return {"error": f"Не удалось получить подписчиков: {str(e)}"}
            
            # Получаем подписки с ограничением и большими задержками
            logger.info("Получаю список подписок...")
            count = 0
            try:
                for follow in profile.get_followees():
                    if count >= max_count:
                        break
                        
                    await self.wait_for_rate_limit()
                    
                    user_info = InstagramUser(
                        username=follow.username,
                        full_name=follow.full_name,
                        followers_count=follow.followers,
                        profile_pic_url=follow.profile_pic_url,
                        is_verified=follow.is_verified,
                        is_private=follow.is_private
                    )
                    following.append(user_info)
                    count += 1
                    
                    if count % 10 == 0:
                        logger.info(f"Получено подписок: {count}")
                        await asyncio.sleep(random.uniform(10, 20))
                        
            except Exception as e:
                logger.error(f"Ошибка получения подписок: {e}")
                if not following:
                    return {"error": f"Не удалось получить подписки: {str(e)}"}
            
            logger.info(f"Анализ завершен. Подписчиков: {len(followers)}, Подписок: {len(following)}")
            
            return {
                "followers": followers,
                "following": following
            }
            
        except Exception as e:
            logger.error(f"Критическая ошибка анализа профиля {username}: {e}")
            return {"error": str(e)}
    
    def find_non_mutual(self, followers: List[InstagramUser], following: List[InstagramUser]) -> List[InstagramUser]:
        """Поиск невзаимных подписок с улучшенной сортировкой"""
        follower_usernames = {user.username.lower() for user in followers}
        
        non_mutual = []
        for user in following:
            if user.username.lower() not in follower_usernames:
                non_mutual.append(user)
        
        # Сортировка: сначала обычные пользователи, затем знаменитости
        def sort_key(user):
            if user.followers_count < 1000:
                return (0, user.followers_count)  # Микро-блоггеры
            elif user.followers_count < 10000:
                return (1, user.followers_count)  # Обычные пользователи
            elif user.followers_count < 100000:
                return (2, user.followers_count)  # Средние аккаунты
            else:
                return (3, user.followers_count)  # Знаменитости
        
        non_mutual.sort(key=sort_key)
        
        logger.info(f"Найдено невзаимных подписок: {len(non_mutual)}")
        return non_mutual

class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.analyzer = InstagramAnalyzer()
        self.application = Application.builder().token(token).build()
        self.active_analyses = {}
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_message = """
🤖 **Instagram Analyzer Bot v2.0**

Привет! Я помогу найти невзаимные подписки в Instagram.

**Команды:**
/analyze @username - анализ невзаимных подписок (до 500)
/profile @username - информация о профиле
/status - статус анализа

**⚡ Особенности:**
✅ Увеличенные задержки для безопасности (5-15 сек)
✅ Анализ до 500 подписчиков/подписок
✅ Умная сортировка результатов
✅ Прямые ссылки на профили
✅ Фото профилей по кнопке

**⚠️ ВАЖНО:**
- Анализ занимает 10-30 минут
- Работает только с открытыми профилями
- Не запускай несколько анализов одновременно
- Используй осторожно (риск блокировки Instagram)
        """
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def analyze_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Анализ невзаимных подписок"""
        if not context.args:
            await update.message.reply_text("Укажите username: /analyze @username")
            return
        
        username = context.args[0]
        user_id = update.effective_user.id
        
        if user_id in self.active_analyses:
            await update.message.reply_text("❌ У вас уже запущен анализ. Дождитесь завершения или используйте /status")
            return
        
        self.active_analyses[user_id] = {"username": username, "start_time": datetime.now()}
        
        await update.message.reply_text("🔍 Запускаю анализ... Это займет 10-30 минут в зависимости от размера профиля.")
        
        try:
            # Получаем информацию о профиле
            profile = await self.analyzer.get_profile_info(username)
            if not profile:
                await update.message.reply_text("❌ Профиль не найден или временно недоступен")
                del self.active_analyses[user_id]
                return
            
            if profile.is_private:
                await update.message.reply_text("❌ Профиль закрытый. Анализ невозможен.")
                del self.active_analyses[user_id]
                return
            
            await update.message.reply_text(f"""
📊 **Начинаю анализ:**
👤 Профиль: @{profile.username} ({profile.full_name})
👥 Подписчиков: {profile.followers_count:,}
📤 Подписок: Загружаю...
⏰ Примерное время: {max(10, min(30, profile.followers_count // 100))} минут

🔄 Собираю данные с увеличенными задержками для безопасности...
            """, parse_mode='Markdown')
            
            # Анализируем с ограничениями
            max_analysis = min(500, profile.followers_count // 2)  # Ограничиваем для безопасности
            data = await self.analyzer.get_followers_and_following(username, max_count=max_analysis)
            
            if "error" in data:
                await update.message.reply_text(f"❌ Ошибка: {data['error']}")
                del self.active_analyses[user_id]
                return
            
            # Находим невзаимные подписки
            non_mutual = self.analyzer.find_non_mutual(data["followers"], data["following"])
            
            if not non_mutual:
                await update.message.reply_text("✅ Все проанализированные подписки взаимные!")
                del self.active_analyses[user_id]
                return
            
            await self.send_analysis_results(update, non_mutual, len(data["followers"]), len(data["following"]))
            
        except Exception as e:
            logger.error(f"Ошибка анализа: {e}")
            await update.message.reply_text(f"❌ Произошла ошибка: {str(e)}")
        finally:
            if user_id in self.active_analyses:
                del self.active_analyses[user_id]
    
    async def send_analysis_results(self, update: Update, non_mutual: List[InstagramUser], followers_count: int, following_count: int):
        """Отправка результатов анализа"""
        # Сводная информация
        summary = f"""
🎉 **Анализ завершен!**

📈 **Статистика:**
👥 Проанализировано подписчиков: {followers_count}
📤 Проанализировано подписок: {following_count}
❌ Невзаимных подписок: {len(non_mutual)}

🎯 **Категории невзаимных:**
        """
        
        # Категоризируем
        micro = [u for u in non_mutual if u.followers_count < 1000]
        regular = [u for u in non_mutual if 1000 <= u.followers_count < 10000]
        medium = [u for u in non_mutual if 10000 <= u.followers_count < 100000]
        celebrities = [u for u in non_mutual if u.followers_count >= 100000]
        
        summary += f"""
🔹 Микро-блоггеры (<1k): {len(micro)}
👤 Обычные пользователи (1k-10k): {len(regular)}
🌟 Средние аккаунты (10k-100k): {len(medium)}
⭐ Знаменитости (100k+): {len(celebrities)}
        """
        
        await update.message.reply_text(summary, parse_mode='Markdown')
        
        # Отправляем результаты порциями
        chunk_size = 8
        
        for i in range(0, len(non_mutual), chunk_size):
            chunk = non_mutual[i:i + chunk_size]
            
            message_text = f"📋 **Невзаимные подписки ({i+1}-{min(i+chunk_size, len(non_mutual))} из {len(non_mutual)}):**\n\n"
            
            keyboard = []
            
            for user in chunk:
                # Определяем иконку
                if user.followers_count >= 100000:
                    icon = "⭐"
                elif user.followers_count >= 10000:
                    icon = "🌟"
                elif user.followers_count >= 1000:
                    icon = "👤"
                else:
                    icon = "🔹"
                
                verified = "✅" if user.is_verified else ""
                private = "🔒" if user.is_private else ""
                
                message_text += f"{icon} **[{user.full_name}](https://instagram.com/{user.username})** {verified}{private}\n"
                message_text += f"   @{user.username} • {user.followers_count:,} подписчиков\n\n"
                
                # Кнопка для фото
                keyboard.append([
                    InlineKeyboardButton(
                        f"📷 {user.username[:15]}{'...' if len(user.username) > 15 else ''}", 
                        callback_data=f"photo_{user.username}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                message_text,
                parse_mode='Markdown',
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            
            await asyncio.sleep(1)  # Задержка между отправками
    
    async def check_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка статуса анализа"""
        user_id = update.effective_user.id
        
        if user_id not in self.active_analyses:
            await update.message.reply_text("📊 У вас нет активных анализов")
            return
        
        analysis = self.active_analyses[user_id]
        elapsed = datetime.now() - analysis["start_time"]
        
        status_message = f"""
⏳ **Статус анализа:**

👤 Профиль: @{analysis["username"]}
⏰ Прошло времени: {elapsed.total_seconds() / 60:.1f} минут

🔄 Анализ продолжается с безопасными задержками...
Ожидайте завершения.
        """
        
        await update.message.reply_text(status_message, parse_mode='Markdown')
    
    async def get_profile_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение информации о профиле"""
        if not context.args:
            await update.message.reply_text("Укажите username: /profile @username")
            return
        
        username = context.args[0]
        
        profile = await self.analyzer.get_profile_info(username)
        
        if not profile:
            await update.message.reply_text("❌ Профиль не найден")
            return
        
        message = f"""
📱 **Профиль Instagram**

👤 **Имя:** {profile.full_name}
🔗 **Username:** @{profile.username}
👥 **Подписчиков:** {profile.followers_count:,}
✅ **Верифицирован:** {'Да' if profile.is_verified else 'Нет'}
🔒 **Приватный:** {'Да' if profile.is_private else 'Нет'}

🔗 [Открыть профиль](https://instagram.com/{profile.username})
        """
        
        keyboard = [[
            InlineKeyboardButton("📷 Показать фото профиля", callback_data=f"photo_{profile.username}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    
    async def show_profile_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ фото профиля"""
        query = update.callback_query
        await query.answer()
        
        username = query.data.replace("photo_", "")
        
        try:
            profile = await self.analyzer.get_profile_info(username)
            
            if not profile:
                await query.edit_message_text("❌ Не удалось получить информацию о профиле")
                return
            
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=profile.profile_pic_url,
                caption=f"📷 Фото профиля @{profile.username}\n🔗 https://instagram.com/{profile.username}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка получения фото: {e}")
            await query.edit_message_text("❌ Не удалось загрузить фото профиля")
    
    def run(self):
        """Запуск бота"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("analyze", self.analyze_profile))
        self.application.add_handler(CommandHandler("profile", self.get_profile_info))
        self.application.add_handler(CommandHandler("status", self.check_status))
        self.application.add_handler(CallbackQueryHandler(self.show_profile_photo, pattern="^photo_"))
        
        print("🤖 Бот запущен...")
        logger.info("Bot started successfully")
        self.application.run_polling()

if __name__ == "__main__":
    BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Установи токен бота в переменную BOT_TOKEN")
        exit(1)
    
    try:
        bot = TelegramBot(BOT_TOKEN)
        bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"❌ Критическая ошибка: {e}")
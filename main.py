import os
import uuid
import requests
import telebot
import time
import logging
from bs4 import BeautifulSoup
from flask import Flask, render_template_string
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

# Настройка логирования для Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.environ.get("BOT_TOKEN")
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 5000))

if not TOKEN:
    logger.error("❌ BOT_TOKEN missing!")
    time.sleep(5)
    exit(1)

# Инициализация Flask и БД
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

bot = telebot.TeleBot(TOKEN)

# --- МОДЕЛЬ БАЗЫ ДАННЫХ ---
class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)
    user_id = db.Column(db.BigInteger)

# --- УЛУЧШЕННЫЙ ПАРСЕР OLX ---
def parse_olx(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Заголовок (OLX использует h4 или h1)
        title_node = soup.find('h1') or soup.find('h4')
        title = title_node.get_text(strip=True) if title_node else "Товар без названия"
        
        # Цена (ищем по специфичному атрибуту OLX)
        price_node = soup.select_one('h3') or soup.select_one('[data-testid="ad-price-container"]')
        price = price_node.get_text(strip=True) if price_node else "Цена не указана"
        
        # Картинка
        img_node = soup.select_one('img.css-1bmv9io') or soup.find('img')
        image = img_node['src'] if img_node and img_node.has_attr('src') else "https://via.placeholder.com/400"
        
        return {"title": title, "price": price, "image": image}
    except Exception as e:
        logger.error(f"Parsing error: {e}")
        raise e

# --- ВЕБ-ИНТЕРФЕЙС ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ p.title }}</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #f2f4f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .card { background: white; width: 90%; max-width: 400px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); overflow: hidden; text-align: center; }
        .img { width: 100%; height: 250px; object-fit: contain; background: #fff; }
        .info { padding: 20px; text-align: left; }
        h1 { font-size: 18px; color: #002f34; margin: 0 0 10px; }
        .price { font-size: 22px; font-weight: bold; color: #002f34; }
        .btn { display: block; background: #002f34; color: white; text-align: center; padding: 12px; margin-top: 20px; border-radius: 6px; text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <img src="{{ p.image_url }}" class="img">
        <div class="info">
            <h1>{{ p.title }}</h1>
            <div class="price">{{ p.price }}</div>
            <a href="#" class="btn">КУПИТЬ</a>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def health(): return "OK", 200

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template_string(HTML_TEMPLATE, p=p)

# --- ОБРАБОТКА БОТА ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "👋 Привет! Пришли ссылку на OLX.ua или OLX.ro")

@bot.message_handler(func=lambda m: True)
def handle_msg(message):
    url = message.text
    if "olx.ua" in url or "olx.ro" in url:
        status_msg = bot.send_message(message.chat.id, "⌛ Собираю данные о товаре...")
        try:
            data = parse_olx(url)
            
            with app.app_context():
                new_item = Product(
                    title=data['title'],
                    price=data['price'],
                    image_url=data['image'],
                    user_id=message.from_user.id
                )
                db.session.add(new_item)
                db.session.commit()
                
                link = f"https://{DOMAIN}/item/{new_item.id}"
                response_text = f"✅ **Готово!**\n\n📌 {data['title']}\n💰 {data['price']}\n\n🔗 Ссылка: {link}"
                bot.edit_message_text(response_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
                logger.info(f"Successfully processed link for user {message.from_user.id}")
        
        except Exception as e:
            bot.edit_message_text(f"❌ Ошибка парсинга. Проверь ссылку.", message.chat.id, status_msg.message_id)
            logger.error(f"Error handling message: {e}")

# --- ЗАПУСК ---
def run_flask():
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Сначала запускаем Flask в фоне
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    logger.info("🚀 Бот запускается...")
    # Запускаем бота в основном потоке
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

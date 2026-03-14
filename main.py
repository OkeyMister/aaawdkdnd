import os
import uuid
import requests
import telebot
import time
from bs4 import BeautifulSoup
from flask import Flask, render_template_string
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

# --- КОНФИГУРАЦИЯ ---
# Используем .get() и добавляем проверку
TOKEN = os.environ.get("BOT_TOKEN")
# Railway выдает домен с https:// или без, приводим к чистому виду
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 5000))

if not TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не найдена!")
    # Даем логам время зафиксироваться перед падением
    time.sleep(10)
    exit(1)

# Инициализация Базы данных
app = Flask(__name__)
# Если DATABASE_URL нет, используем локальную sqlite (для тестов)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Инициализация Бота (теперь TOKEN точно не None)
bot = telebot.TeleBot(TOKEN)

# --- МОДЕЛЬ БАЗЫ ДАННЫХ ---
class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)
    user_id = db.Column(db.BigInteger)

# --- ПАРСЕР OLX ---
def parse_olx(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    r = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    # Пытаемся достать заголовок
    title_tag = soup.find('h1') or soup.find('h4')
    title = title_tag.text.strip() if title_tag else "Товар"
    
    # Улучшенный поиск цены для OLX
    price_tag = soup.find('h3') or soup.find('h2') or soup.find('div', {'data-testid': 'ad-price-container'})
    price = price_tag.text.strip() if price_tag else "Цена по запросу"
    
    # Ищем фото товара
    img_tag = soup.find('img', {'class': 'css-1bmv9io'}) or soup.find('img')
    image = img_tag['src'] if img_tag and img_tag.has_attr('src') else "https://via.placeholder.com/400"
    
    return {"title": title, "price": price, "image": image}

# --- ВЕБ-САЙТ ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ p.title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f2f4f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .card { background: white; width: 95%; max-width: 400px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); overflow: hidden; text-align: center; padding-bottom: 25px; }
        .img-box { width: 100%; height: 300px; background: url('{{ p.image_url }}') center/contain no-repeat; background-color: #fff; }
        h1 { font-size: 20px; color: #002f34; padding: 15px 20px; margin: 0; text-align: left; }
        .price { font-size: 24px; font-weight: bold; color: #002f34; margin: 10px 20px; text-align: left; }
        .btn { display: block; background: #002f34; color: white; padding: 14px; margin: 0 20px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; transition: background 0.2s; }
        .btn:hover { background: #004f56; }
    </style>
</head>
<body>
    <div class="card">
        <div class="img-box"></div>
        <h1>{{ p.title }}</h1>
        <div class="price">{{ p.price }}</div>
        <a href="#" class="btn">Сообщение</a>
    </div>
</body>
</html>
"""

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template_string(HTML_TEMPLATE, p=p)

# --- ОБРАБОТКА БОТА ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Пришли мне ссылку на товар с OLX (ua или ro).")

@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    if "olx.ua" in message.text or "olx.ro" in message.text:
        wait_msg = bot.send_message(message.chat.id, "⌛ Извлекаю данные...")
        try:
            # Парсим
            data = parse_olx(message.text)
            
            # Сохраняем в БД
            new_item = Product(
                title=data['title'],
                price=data['price'],
                image_url=data['image'],
                user_id=message.from_user.id
            )
            
            with app.app_context():
                db.session.add(new_item)
                db.session.commit()
                
                # Формируем ссылку. Используем https:// принудительно
                final_url = f"https://{DOMAIN}/item/{new_item.id}"
                bot.edit_message_text(f"✅ Готово!\n\n📌 *{data['title']}*\n💰 {data['price']}\n\n🔗 Ссылка: {final_url}", 
                                     message.chat.id, wait_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ Ошибка: {str(e)}", message.chat.id, wait_msg.message_id)

# --- ЗАПУСК ---
def run_flask():
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    # Запуск Flask
    t = Thread(target=run_flask)
    t.daemon = True # Поток умрет при выходе из основной программы
    t.start()
    
    # Запуск бота
    print("🚀 Бот запущен...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

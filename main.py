import os
import uuid
import requests
import telebot
from bs4 import BeautifulSoup
from flask import Flask, render_template_string
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
DOMAIN = os.getenv("RAILWAY_STATIC_URL", "localhost:5000")
PORT = int(os.getenv("PORT", 5000))

# Инициализация Flask и Базы данных
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Инициализация Бота
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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    title = soup.find('h1').text.strip() if soup.find('h1') else "Товар"
    # Поиск цены (пробуем разные селекторы OLX)
    price_tag = soup.find('h3') or soup.find('h2') or soup.find('div', {'data-testid': 'ad-price-container'})
    price = price_tag.text.strip() if price_tag else "Цена не указана"
    
    img_tag = soup.find('img')
    image = img_tag['src'] if img_tag else "https://via.placeholder.com/400"
    
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
        body { font-family: sans-serif; background-color: #f2f4f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .card { background: white; width: 90%; max-width: 380px; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); overflow: hidden; text-align: center; padding-bottom: 25px; }
        .img-box { width: 100%; height: 280px; background: url('{{ p.image_url }}') center/cover; }
        h1 { font-size: 22px; color: #002f34; padding: 15px; margin: 0; }
        .price { font-size: 26px; font-weight: bold; color: #002f34; margin: 10px 0 20px; }
        .btn { background: #002f34; color: white; padding: 12px 40px; border-radius: 8px; text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <div class="img-box"></div>
        <h1>{{ p.title }}</h1>
        <div class="price">{{ p.price }}</div>
        <a href="#" class="btn">КУПИТЬ</a>
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
    bot.reply_to(message, "👋 Привет! Пришли мне ссылку на товар с OLX.")

@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    if "olx.ua" in message.text or "olx.ro" in message.text:
        wait_msg = bot.send_message(message.chat.id, "⌛ Обработка ссылки...")
        try:
            data = parse_olx(message.text)
            new_item = Product(
                title=data['title'],
                price=data['price'],
                image_url=data['image'],
                user_id=message.from_user.id
            )
            with app.app_context():
                db.session.add(new_item)
                db.session.commit()
                # Ссылка на сайт
                final_url = f"https://{DOMAIN}/item/{new_item.id}"
                bot.edit_message_text(f"✅ Готово! Ваша страница:\n{final_url}", message.chat.id, wait_msg.message_id)
        except Exception as e:
            bot.edit_message_text(f"❌ Ошибка при парсинге: {e}", message.chat.id, wait_msg.message_id)

# --- ЗАПУСК ---
def run_flask():
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    # Запускаем Flask в потоке
    Thread(target=run_flask).start()
    # Запускаем бота
    bot.infinity_polling()

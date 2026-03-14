import os
import uuid
import requests
import telebot
import time
import logging
from bs4 import BeautifulSoup
from flask import Flask, render_template # Оставляем render_template
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

# --- НАСТРОЙКИ ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 8080))

# ВАЖНО: template_folder='.' говорит Flask искать HTML рядом с main.py
app = Flask(__name__, template_folder='.') 
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

bot = telebot.TeleBot(TOKEN)

# --- МОДЕЛЬ БД ---
class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)
    user_id = db.Column(db.BigInteger)

# --- ПАРСЕР ---
def parse_olx(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        title_node = soup.find('h1') or soup.find('h4')
        title = title_node.get_text(strip=True) if title_node else "Товар"
        price_node = soup.select_one('h3') or soup.select_one('[data-testid="ad-price-container"]')
        price = price_node.get_text(strip=True) if price_node else "Цена не указана"
        img_node = soup.select_one('img.css-1bmv9io') or soup.find('img')
        image = img_node['src'] if img_node and img_node.has_attr('src') else "https://via.placeholder.com/400"
        return {"title": title, "price": price, "image": image}
    except Exception as e:
        logger.error(f"Parse error: {e}")
        raise e

# --- РОУТЫ ---
@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    # Теперь он найдет item.html в корне проекта
    return render_template('item.html', p=p)

# --- БОТ ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "👋 Привет! Кидай ссылку.")

@bot.message_handler(func=lambda m: True)
def handle_msg(message):
    url = message.text
    if "olx" in url:
        status_msg = bot.send_message(message.chat.id, "⌛ Делаю...")
        try:
            data = parse_olx(url)
            with app.app_context():
                new_item = Product(title=data['title'], price=data['price'], image_url=data['image'], user_id=message.from_user.id)
                db.session.add(new_item)
                db.session.commit()
                bot.edit_message_text(f"✅ Готово!\n\n🔗 Ссылка: https://{DOMAIN}/item/{new_item.id}", message.chat.id, status_msg.message_id)
        except Exception as e:
            bot.edit_message_text(f"❌ Ошибка", message.chat.id, status_msg.message_id)

if __name__ == '__main__':
    Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False), daemon=True).start()
    bot.infinity_polling()

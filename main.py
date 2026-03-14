import os
import uuid
import requests
import telebot
import logging
from bs4 import BeautifulSoup
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 8080))

# template_folder='.' заставляет Flask искать HTML в корне, а не в templates/
app = Flask(__name__, template_folder='.')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

bot = telebot.TeleBot(TOKEN)

class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)

def parse_olx(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')
    title = (soup.find('h1') or soup.find('h4')).get_text(strip=True)
    price = (soup.select_one('h3') or soup.select_one('[data-testid="ad-price-container"]')).get_text(strip=True)
    img = soup.select_one('img.css-1bmv9io')['src']
    return {"title": title, "price": price, "image": img}

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template('item.html', p=p)

@bot.message_handler(func=lambda m: "olx" in m.text)
def handle_msg(message):
    try:
        data = parse_olx(message.text)
        with app.app_context():
            new_item = Product(title=data['title'], price=data['price'], image_url=data['image'])
            db.session.add(new_item)
            db.session.commit()
            bot.reply_to(message, f"✅ Готово!\n\n🔗 Ссылка: https://{DOMAIN}/item/{new_item.id}")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка парсинга")

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False)).start()
    bot.infinity_polling()

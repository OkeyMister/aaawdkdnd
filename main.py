import os
import uuid
import requests
import telebot
import logging
import time
from bs4 import BeautifulSoup
from flask import Flask, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 8080))

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
    # Додаємо правильні заголовки, щоб OLX не видавав "Повідомлення"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Більш точні селектори для назви та ціни
        title_tag = soup.find('h1', {'data-cy': 'ad_title'}) or soup.find('h4') or soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else "Товар без назви"

        price_tag = soup.find('h3') or soup.select_one('[data-testid="ad-price-container"]')
        # Очищаємо ціну від "грн", "Договірна" тощо, залишаємо тільки цифри для краси
        price_raw = price_tag.get_text(strip=True) if price_tag else "0"
        price = "".join(filter(str.isdigit, price_raw)) or price_raw

        img_tag = soup.select_one('img.css-1bmv9io') or soup.find('img', {'src': True})
        img = img_tag['src'] if img_tag else "https://via.placeholder.com/400"

        return {"title": title, "price": price, "image": img}
    except Exception as e:
        logger.error(f"Парсинг помилка: {e}")
        return {"title": "Помилка завантаження", "price": "0", "image": ""}

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template('item.html', p=p)

# Роут для сторінки банків
@app.route('/banks.html')
def banks_page():
    return "<h1>Сторінка вибору банку (створіть banks.html)</h1>"

@bot.message_handler(func=lambda m: "olx.ua" in m.text or "olx.ro" in m.text)
def handle_msg(message):
    try:
        data = parse_olx(message.text)
        with app.app_context():
            new_item = Product(title=data['title'], price=data['price'], image_url=data['image'])
            db.session.add(new_item)
            db.session.commit()
            bot.reply_to(message, f"✅ Посилання готове:\nhttps://{DOMAIN}/item/{new_item.id}")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка при создании ссылки")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    time.sleep(2)
    bot.remove_webhook()
    bot.infinity_polling(none_stop=True)

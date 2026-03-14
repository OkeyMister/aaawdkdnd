import os
import uuid
import telebot
import logging
import time
import requests  # Для запитів до Scrappey
from bs4 import BeautifulSoup
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Налаштування
TOKEN = os.environ.get("BOT_TOKEN")
SCRAPPEY_KEY = os.environ.get("SCRAPPEY_API_KEY") # Твій ключ Scrappey
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 8080))

app = Flask(__name__, template_folder='.')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
db = SQLAlchemy(app)

bot = telebot.TeleBot(TOKEN)

class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)

def parse_olx(url):
    logger.info(f"Відправляю запит на Scrappey для: {url}")
    
    # Формуємо запит до Scrappey
    payload = {
        'cmd': 'request.get',
        'url': url,
        'browser': True,        # Обов'язково запускаємо браузер
        'proxy': True           # Використовуємо їхні проксі для обходу блоку
    }
    
    try:
        # Відправляємо запит до API Scrappey
        response = requests.post(
            f'https://publisher.scrappey.com/?key={SCRAPPEY_KEY}', 
            json=payload, 
            timeout=30
        )
        res_data = response.json()
        
        # Scrappey повертає HTML у полі 'solution' -> 'response'
        html = res_data.get('solution', {}).get('response', '')
        
        if not html:
            logger.error("Scrappey не повернув HTML")
            return None

        soup = BeautifulSoup(html, 'html.parser')

        # 1. Назва
        title_tag = soup.find('h1', {'data-cy': 'ad_title'}) or soup.find('h4')
        title = title_tag.get_text(strip=True) if title_tag else "Товар без назви"

        # 2. Ціна
        price_tag = soup.select_one('[data-testid="ad-price-container"]') or soup.find('h3')
        price_raw = price_tag.get_text(strip=True) if price_tag else "0"
        price = "".join(filter(str.isdigit, price_raw)) or "0"

        # 3. Картинка
        img_tag = soup.select_one('img.css-1bmv9io') or soup.find('img', {'src': True})
        image = img_tag['src'] if img_tag else "https://via.placeholder.com/400"

        return {"title": title, "price": price, "image": image}

    except Exception as e:
        logger.error(f"Помилка Scrappey: {e}")
        return None

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template('item.html', p=p)

@bot.message_handler(func=lambda m: "olx" in m.text.lower())
def handle_msg(message):
    processing = bot.reply_to(message, "⏳ Scrappey обходить захист OLX, зачекайте...")
    
    data = parse_olx(message.text)
    
    if data:
        with app.app_context():
            new_item = Product(title=data['title'], price=data['price'], image_url=data['image'])
            db.session.add(new_item)
            db.session.commit()
            
            bot.delete_message(message.chat.id, processing.message_id)
            bot.reply_to(message, f"✅ **Готово!**\nhttps://{DOMAIN}/item/{new_item.id}")
    else:
        bot.edit_message_text("❌ Навіть Scrappey не зміг пробитися. Перевір ліміти або посилання.", message.chat.id, processing.message_id)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False), daemon=True).start()
    bot.infinity_polling()

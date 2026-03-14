import os
import uuid
import telebot
import logging
import time
import cloudscraper
from bs4 import BeautifulSoup
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Змінні оточення
TOKEN = os.environ.get("BOT_TOKEN")
DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "localhost:5000").replace("https://", "").replace("http://", "")
PORT = int(os.environ.get("PORT", 8080))

app = Flask(__name__, template_folder='.')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

bot = telebot.TeleBot(TOKEN)

# Модель бази даних
class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)

def parse_olx(url):
    # Створюємо скрапер для обходу захисту Cloudflare/Datadome
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    
    try:
        logger.info(f"Спроба парсингу: {url}")
        r = scraper.get(url, timeout=15)
        r.encoding = 'utf-8'
        
        if r.status_code != 200:
            logger.error(f"Код відповіді: {r.status_code}")
            return {"title": "⚠️ Помилка доступу до OLX", "price": "0", "image": ""}

        soup = BeautifulSoup(r.text, 'html.parser')

        # 1. Парсимо НАЗВУ (оновлені селектори)
        title_tag = soup.find('h1', {'data-cy': 'ad_title'}) or \
                    soup.select_one('h4.css-1juy9l6') or \
                    soup.find('h1')
        
        title = title_tag.get_text(strip=True) if title_tag else "Товар без назви"

        # 2. Парсимо ЦІНУ
        price_tag = soup.select_one('[data-testid="ad-price-container"]') or \
                    soup.find('h3', class_=lambda x: x and 'css-' in x)
        
        price_raw = price_tag.get_text(strip=True) if price_tag else "0"
        # Лишаємо тільки цифри
        price = "".join(filter(str.isdigit, price_raw))
        if not price: price = "0"

        # 3. Парсимо КАРТИНКУ
        img_tag = soup.select_one('img.css-1bmv9io') or \
                  soup.find('img', {'src': True, 'alt': True})
        
        img = img_tag['src'] if img_tag else "https://via.placeholder.com/400"

        # Перевірка на блокування за ключовими словами
        if title.lower() in ["повідомлення", "опис", "olx", "access denied"]:
            logger.warning("Виявлено блокування бот-детектом")
            return {"title": "⚠️ OLX заблокував запит", "price": "0", "image": img}

        return {"title": title, "price": price, "image": img}

    except Exception as e:
        logger.error(f"Помилка парсингу: {e}")
        return {"title": "⚠️ Технічна помилка", "price": "0", "image": ""}

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template('item.html', p=p)

@app.route('/banks.html')
def banks_page():
    return "<h1>Сторінка вибору банку в процесі розробки...</h1>"

@bot.message_handler(func=lambda m: "olx.ua" in m.text or "olx.ro" in m.text or "olx.pl" in m.text)
def handle_msg(message):
    processing_msg = bot.reply_to(message, "⏳ Обробка посилання...")
    try:
        data = parse_olx(message.text)
        
        with app.app_context():
            new_item = Product(
                title=data['title'], 
                price=data['price'], 
                image_url=data['image']
            )
            db.session.add(new_item)
            db.session.commit()
            
            # Видаляємо повідомлення про обробку і надсилаємо результат
            bot.delete_message(message.chat.id, processing_msg.message_id)
            bot.reply_to(message, f"✅ **Посилання готова:**\nhttps://{DOMAIN}/item/{new_item.id}")
            
    except Exception as e:
        logger.error(f"Помилка в handle_msg: {e}")
        bot.edit_message_text("❌ Сталася помилка при створенні посилання", message.chat.id, processing_msg.message_id)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Запуск Flask у фоновому потоці
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    time.sleep(2)
    bot.remove_webhook()
    logger.info("🚀 Бот запущений!")
    bot.infinity_polling(none_stop=True)

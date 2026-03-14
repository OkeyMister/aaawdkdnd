import os
import uuid
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string
from aiogram import Bot, Dispatcher, types, executor
from flask_sqlalchemy import SQLAlchemy
from threading import Thread

# Настройки
TOKEN = os.getenv("BOT_TOKEN")
DOMAIN = os.getenv("RAILWAY_STATIC_URL", "localhost:5000")
PORT = int(os.getenv("PORT", 5000))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///database.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Product(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255))
    price = db.Column(db.String(100))
    image_url = db.Column(db.Text)
    user_id = db.Column(db.BigInteger)

def parse_olx(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, 'html.parser')
    title = soup.find('h1').text.strip() if soup.find('h1') else "Товар"
    price_tag = soup.find('h3') or soup.find('h2')
    price = price_tag.text.strip() if price_tag else "Цена договорная"
    img_tag = soup.find('img')
    image = img_tag['src'] if img_tag else "https://via.placeholder.com/400"
    return {"title": title, "price": price, "image": image}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{{ p.title }}</title>
    <style>
        body { font-family: sans-serif; background: #f2f4f5; display: flex; justify-content: center; padding: 20px; }
        .card { background: white; width: 100%; max-width: 350px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); overflow: hidden; text-align: center; }
        img { width: 100%; height: 250px; object-fit: cover; }
        h1 { font-size: 18px; margin: 15px; }
        .price { font-size: 22px; font-weight: bold; color: #002f34; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="card">
        <img src="{{ p.image_url }}">
        <h1>{{ p.title }}</h1>
        <div class="price">{{ p.price }}</div>
    </div>
</body>
</html>
"""

@app.route('/item/<item_id>')
def show_item(item_id):
    p = Product.query.get_or_404(item_id)
    return render_template_string(HTML_TEMPLATE, p=p)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("Пришли ссылку на OLX!")

@dp.message_handler()
async def handle_link(message: types.Message):
    if "olx." in message.text:
        try:
            data = parse_olx(message.text)
            new_item = Product(title=data['title'], price=data['price'], image_url=data['image'], user_id=message.from_user.id)
            with app.app_context():
                db.session.add(new_item)
                db.session.commit()
                await message.reply(f"✅ Готово: https://{DOMAIN}/item/{new_item.id}")
        except Exception as e:
            await message.reply(f"Ошибка: {e}")

def run_flask():
    with app.app_context(): db.create_all()
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    Thread(target=run_flask).start()
    executor.start_polling(dp, skip_updates=True)

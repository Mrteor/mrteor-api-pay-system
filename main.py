from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
import sqlite3

# 配置
SECRET_KEY = "your-secret-key-keep-it-safe"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app = FastAPI(title="API 付费平台")
app.mount("/static", StaticFiles(directory="static"), name="static")

# 初始化数据库
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, 
                  hashed_password TEXT, 
                  email TEXT, 
                  api_calls INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (order_id TEXT PRIMARY KEY,
                  username TEXT,
                  amount REAL,
                  package_name TEXT,
                  status TEXT DEFAULT "pending")''')
    conn.commit()
    conn.close()

init_db()

# 数据模型
class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class OrderCreate(BaseModel):
    package_name: str

# 工具函数
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_user(username: str):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    if user:
        return {"username": user[0], "hashed_password": user[1], "email": user[2], "api_calls": user[3]}
    return None

def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user:
        return False
    if not verify_password(password, user["hashed_password"]):
        return False
    return user

def create_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user

# 1. 用户注册
@app.post("/register")
def register(user: UserCreate):
    if get_user(user.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    hashed_password = get_password_hash(user.password)
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO users (username, hashed_password, email) VALUES (?, ?, ?)",
              (user.username, hashed_password, user.email))
    conn.commit()
    conn.close()
    return {"msg": "注册成功"}

# 2. 用户登录
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = create_token({"sub": user["username"]})
    return {"access_token": token, "token_type": "bearer"}

# 3. 个人中心
@app.get("/user/me")
def read_current_user(current_user: dict = Depends(get_current_user)):
    return {
        "username": current_user["username"],
        "email": current_user["email"],
        "api_calls": current_user["api_calls"]
    }

# 4. 创建订单（付费）
@app.post("/create-order")
def create_order(order: OrderCreate, current_user: dict = Depends(get_current_user)):
    packages = {
        "basic": {"amount": 29, "calls": 1000},
        "pro": {"amount": 99, "calls": 10000}
    }
    if order.package_name not in packages:
        raise HTTPException(status_code=400, detail="无效套餐")
    
    order_id = f"order_{int(datetime.now().timestamp())}"
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO orders (order_id, username, amount, package_name) VALUES (?, ?, ?, ?)",
              (order_id, current_user["username"], 
               packages[order.package_name]["amount"], 
               order.package_name))
    conn.commit()
    conn.close()
    
    # 模拟支付链接（实际项目替换为真实支付网关）
    pay_url = f"/pay/{order_id}"
    return {"order_id": order_id, "pay_url": pay_url}

# 5. 模拟支付页面
@app.get("/pay/{order_id}")
def pay_page(order_id: str):
    return FileResponse("static/pay.html")

# 6. 支付回调（模拟）
@app.post("/payment-callback/{order_id}")
def payment_callback(order_id: str):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
    order = c.fetchone()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    # 更新订单状态
    c.execute("UPDATE orders SET status='success' WHERE order_id=?", (order_id,))
    
    # 增加用户API调用次数
    package = order[3]
    calls = 1000 if package == "basic" else 10000
    c.execute("UPDATE users SET api_calls = api_calls + ? WHERE username=?", (calls, order[1]))
    
    conn.commit()
    conn.close()
    return {"msg": "支付成功，已为你增加API调用次数"}

# 7. 示例API接口（需要登录）
@app.get("/api/hello")
def hello_api(current_user: dict = Depends(get_current_user)):
    if current_user["api_calls"] <= 0:
        raise HTTPException(status_code=403, detail="API调用次数不足，请购买套餐")
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("UPDATE users SET api_calls = api_calls - 1 WHERE username=?", (current_user["username"],))
    conn.commit()
    conn.close()
    
    return {"msg": f"Hello {current_user['username']}! 这是你的API响应"}

# 8. 前端页面路由
@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.get("/login")
def login_page():
    return FileResponse("static/login.html")

@app.get("/register")
def register_page():
    return FileResponse("static/register.html")

@app.get("/pricing")
def pricing_page():
    return FileResponse("static/pricing.html")


import os

from flask import Flask, request, session, redirect


# 类似拦截器  加上下面函数里标*的东西才算拦截器
def auth():
    # 如果返回登录页面的时候渲染有问题可能是静态js也被拦截了 可以执行不拦截静态目录/static
    if request.path == '/login':
        # 继续向后执行，不拦截
        return

    # 读取cookie&解密获取用户信息
    user_info = session.get('user_info')
    if user_info:
        #如果有值 继续执行 不拦截
        return

    return redirect('/login')

def get_role():
    user_info = session.get("user_info") or {}
    return user_info.get("role")


def get_real_name():
    user_info = session.get('user_info')
    return user_info["real_name"]

def create_app():
    app = Flask(__name__)

    @app.get("/")
    def home():
        """未登录由 before_request 转到登录页；已登录直接进入订单列表。"""
        return redirect("/order/list")
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "development-only-change-me")
    from .views import account
    from .views import order # 从当前目录的 views 模块导入 order 蓝图
    app.register_blueprint(account.ac)# 将 account 蓝图注册到 Flask 应用，使路由生效
    app.register_blueprint(order.od)

    app.before_request(auth)  # *****加拦截器
    app.template_global()(get_real_name)  # 把函数注册到每个模板
    app.template_global()(get_role)
    return app
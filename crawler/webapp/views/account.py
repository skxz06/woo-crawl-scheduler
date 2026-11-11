from flask import Blueprint, render_template, request, redirect,session
from werkzeug.security import check_password_hash, generate_password_hash

from utils import db
# 蓝图对象
ac = Blueprint('account', __name__)

@ac.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        # 渲染模板：去 templates 文件夹找 login.html 并返回给浏览器 路由不变只渲染页面
        return render_template("login.html")
    mobile = request.form.get('mobile')
    pwd = request.form.get('password')

    # 去数据库校验
    # 连接MySQL并执行SQL语句查询用户名密码是否正确
    user_dict = db.fetch_one(
        "select id, password, real_name, role, mobile from userinfo where mobile=%s",
        (mobile,),
    )
    stored = user_dict["password"] if user_dict else ""
    if stored.startswith("scrypt:"):
        password_ok = check_password_hash(stored, pwd)
    else:
        # 兼容尚未迁移的旧明文密码，成功后立即升级成哈希。
        password_ok = stored == pwd
        if password_ok:
            db.execute(
                "update userinfo set password=%s where id=%s",
                (generate_password_hash(pwd), user_dict["id"]),
            )
    if user_dict and password_ok:
        # 登录成功 + 跳转
        session['user_info'] = {"role":user_dict["role"], "real_name":user_dict["real_name"], "id":user_dict["id"], "mobile":user_dict["mobile"]}   # 设置cookie
        return redirect('/order/list') #跳路由，地址栏改变，刷新安全
    return render_template("login.html",error="用户名或密码错误")

@ac.route('/user/list')
def users():
    user = session.get("user_info")
    if user["role"] != 2:
        return redirect("/order/list")
    rows = db.fetch_all(
        """
        SELECT userinfo.id, userinfo.real_name, userinfo.role,
               COUNT(`order`.id) AS order_count
        FROM userinfo
        LEFT JOIN `order` ON `order`.user_id = userinfo.id
        GROUP BY userinfo.id, userinfo.real_name, userinfo.role
        ORDER BY userinfo.id
        """,
        [],
    )
    return render_template("user_list.html", users=rows)
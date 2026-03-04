import subprocess
import tempfile
import os
import sys

from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash  # 密码加密

app = Flask(__name__)
# 如果是生产环境（Vercel），使用内存数据库或环境变量中的数据库URL
if os.environ.get('VERCEL'):
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your-secret-key-here'  # 用于 session，后续登录需要

db = SQLAlchemy(app)

# ---------- 数据模型 ----------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

class Problem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    test_input = db.Column(db.Text, nullable=False)      # 测试用例输入
    expected_output = db.Column(db.Text, nullable=False) # 期望输出
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey('problem.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # 允许匿名提交
    code = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False)    # AC/WA/TLE/RE
    message = db.Column(db.Text)                          # 详细信息
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    problem = db.relationship('Problem')
    user = db.relationship('User')


with app.app_context():
    db.create_all()
    # 初始化题目（如果数据库中没有题目）
    if Problem.query.count() == 0:
        problems = [
            Problem(
                title="A + B 问题",
                description="输入两个整数 a 和 b，输出它们的和。",
                test_input="1 2",
                expected_output="3"
            ),
            Problem(
                title="字符串反转",
                description="输入一个字符串，输出反转后的结果。",
                test_input="hello",
                expected_output="olleh"
            ),
            Problem(
                title="判断奇偶",
                description="输入一个整数，如果它是奇数输出 'odd'，偶数输出 'even'。",
                test_input="5",
                expected_output="odd"
            ),
        ]
        db.session.add_all(problems)
        db.session.commit()



@app.route('/')
def home():
    return "User 表已创建！现在可以访问 /register 注册用户。"

# ---------- 注册路由 ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # 检查用户名是否已存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "用户名已存在，请重新注册。"

        # 创建新用户
        new_user = User(username=username)
        new_user.set_password(password)  # 加密密码
        db.session.add(new_user)
        db.session.commit()

        return f"用户 {username} 注册成功！<br><a href='/register'>返回注册</a>"

    # GET 请求：显示注册表单
    return render_template('register.html')

# ---------- 题目列表 ----------
@app.route('/problems')
def problems():
    problems = Problem.query.all()
    return render_template('problems.html', problems=problems)

# ---------- 单个题目提交页面 ----------
@app.route('/problem/<int:problem_id>', methods=['GET', 'POST'])
def problem_submit(problem_id):
    problem = Problem.query.get_or_404(problem_id)
    result = None
    if request.method == 'POST':
        code = request.form['code']
        # 调用判题函数
        result = judge_code(code, problem.test_input, problem.expected_output)

        # 保存提交记录（暂时使用默认用户ID=1，需要确保存在用户1，或者使用None）
        # 为了简单，我们假设有一个用户ID=1（你可以手动注册一个用户，或者我们自动创建一个游客用户）
        # 如果用户表为空，我们创建一个默认用户
        user = User.query.filter_by(username='guest').first()
        if not user:
            user = User(username='guest')
            user.set_password('guest123')
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        else:
            user_id = user.id

        sub = Submission(
            problem_id=problem.id,
            user_id=user_id,
            code=code,
            status=result['status'],
            message=result['message']
        )
        db.session.add(sub)
        db.session.commit()

    return render_template('problem.html', problem=problem, result=result)


# ---------- 判题核心函数 ----------
def judge_code(user_code, test_input, expected_output, timeout=2):
    """
    判题函数
    :param user_code: 用户提交的代码字符串
    :param test_input: 测试输入字符串
    :param expected_output: 期望输出字符串
    :param timeout: 超时时间（秒）
    :return: 判题结果字典 {'status': 'AC/WA/TLE/RE', 'message': 详细信息}
    """
    # 使用临时文件保存用户代码
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', encoding='utf-8', delete=False) as f:
        f.write(user_code)
        temp_file = f.name

    try:
        # 运行用户代码，传递输入
        result = subprocess.run(
            [sys.executable, temp_file],  # 使用当前 Python 解释器
            input=test_input,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False  # 不抛出 CalledProcessError，我们自己处理返回码
        )

        # 判断运行状态
        if result.returncode != 0:
            return {'status': 'RE', 'message': f'运行时错误:\n{result.stderr}'}

        # 比较输出（去除首尾空白，避免因换行符差异导致WA）
        actual_output = result.stdout.strip()
        expected_output = expected_output.strip()

        if actual_output == expected_output:
            return {'status': 'AC', 'message': '答案正确'}
        else:
            return {'status': 'WA', 'message': f'预期输出:\n{expected_output}\n你的输出:\n{actual_output}'}

    except subprocess.TimeoutExpired:
        return {'status': 'TLE', 'message': f'运行超时（超过{timeout}秒）'}
    except Exception as e:
        return {'status': 'RE', 'message': f'执行异常: {str(e)}'}
    finally:
        # 清理临时文件
        try:
            os.unlink(temp_file)
        except:
            pass


# ---------- 测试判题的页面 ----------
@app.route('/judge', methods=['GET', 'POST'])
def judge_page():
    if request.method == 'POST':
        code = request.form['code']
        test_input = request.form['test_input']
        expected = request.form['expected']
        result = judge_code(code, test_input, expected)
        return f"""
        <h3>判题结果: {result['status']}</h3>
        <pre>{result['message']}</pre>
        <a href="/judge">再测一次</a>
        """
    # GET 请求显示表单
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>代码判题测试</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body class="container mt-5">
        <h2>代码判题测试</h2>
        <form method="post">
            <div class="mb-3">
                <label>Python 代码：</label>
                <textarea name="code" class="form-control" rows="6" required>print(input().strip())</textarea>
            </div>
            <div class="mb-3">
                <label>测试输入：</label>
                <input type="text" name="test_input" class="form-control" value="hello">
            </div>
            <div class="mb-3">
                <label>期望输出：</label>
                <input type="text" name="expected" class="form-control" value="hello">
            </div>
            <button type="submit" class="btn btn-primary">运行判题</button>
        </form>
    </body>
    </html>
    """

if __name__ == '__main__':
    app.run(debug=True)


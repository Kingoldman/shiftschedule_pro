"""依赖安装脚本

解决 32 位 Python 3.13 上 greenlet/httptools 无法编译的问题。
分步安装，跳过不需要的 C 扩展包。

用法：python install.py
"""
import subprocess
import sys


def pip_install(args):
    """执行 pip install 命令"""
    cmd = [sys.executable, "-m", "pip", "install"] + args
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [警告] 命令返回非零，继续尝试...")


def main():
    print("=" * 50)
    print("隔壁小王爱值班 - 后端依赖安装")
    print("=" * 50)

    # 第一步：SQLAlchemy 不带 greenlet（我们只用同步模式）
    pip_install(["sqlalchemy>=2.0.0", "--no-deps"])
    pip_install(["typing-extensions"])

    # 第二步：核心包不带可选依赖
    pip_install([
        "uvicorn>=0.20.0", "fastapi>=0.100.0", "pydantic>=2.0.0", "pydantic-settings>=2.0.0",
        "python-multipart>=0.0.6", "bcrypt>=4.0.0", "PyJWT>=2.0.0", "python-dateutil>=2.8.0",
        "--no-deps",
    ])

    # 第三步：补全这些包的纯 Python 依赖
    # 注意：pydantic-core 必须指定版本 2.46.4，否则与 pydantic 2.13.4 不兼容
    pip_install([
        "starlette", "anyio", "idna", "sniffio",
        "annotated-types",
        "pydantic-core==2.46.4",  # 关键：锁定版本
        "click", "h11",
        "colorama", "python-dotenv", "six",
        "annotated-doc", "typing-inspection",
    ])

    # 验证
    print("\n" + "=" * 50)
    print("验证安装...")
    try:
        import fastapi
        import uvicorn
        import sqlalchemy
        import pydantic
        import bcrypt
        import jwt
        print("所有核心包安装成功！")
        print(f"  fastapi    {fastapi.__version__}")
        print(f"  uvicorn    {uvicorn.__version__}")
        print(f"  sqlalchemy {sqlalchemy.__version__}")
        print(f"  pydantic   {pydantic.__version__}")
    except ImportError as e:
        print(f"安装不完整: {e}")
        print("请检查上方的错误信息")

    print("=" * 50)


if __name__ == "__main__":
    main()
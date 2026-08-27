"""Label Studio 1.23 legacy token 修复（首次启动后运行一次）。

新版 LS 默认禁用 legacy API token（Authorization: Token xxx 会 401），
本脚本把当前组织的 legacy_api_tokens_enabled 置为 1。
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "data" / "label_studio.sqlite3"


def main():
    if not DB.exists():
        print(f"未找到数据库：{DB}\n请先启动一次 labelstudio.bat")
        return 1
    conn = sqlite3.connect(DB)
    rows = list(conn.execute("SELECT organization_id, legacy_api_tokens_enabled FROM jwt_auth_jwtsettings"))
    if not rows:
        print("无组织设置，跳过")
        conn.close()
        return 0
    conn.execute("UPDATE jwt_auth_jwtsettings SET legacy_api_tokens_enabled = 1")
    conn.commit()
    print("已启用 legacy token：", list(conn.execute(
        "SELECT organization_id, legacy_api_tokens_enabled FROM jwt_auth_jwtsettings")))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

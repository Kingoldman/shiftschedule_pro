"""认证相关接口"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.core.security import verify_password, create_access_token, hash_password
from app.models.admin import Admin
from app.schemas.admin import AdminLogin, Token, AdminOut

router = APIRouter()


@router.post("/login", response_model=Token)
def login(body: AdminLogin, db: Session = Depends(get_db)):
    """管理员登录，返回 JWT"""
    admin = db.query(Admin).filter(Admin.username == body.username).first()
    if not admin or not verify_password(body.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    # sub 是 JWT 标准字段，表示主体（subject）
    token = create_access_token({"sub": str(admin.id)})
    return Token(access_token=token)


@router.get("/me", response_model=AdminOut)
def get_me(current: Admin = Depends(get_current_admin)):
    """获取当前登录管理员信息"""
    return current


@router.post("/change-password")
def change_password(
    payload: dict,
    current: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改密码

    前端传入 {old_password, new_password}
    """
    old = payload.get("old_password", "")
    new = payload.get("new_password", "")
    if not new or len(new) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if not verify_password(old, current.hashed_password):
        raise HTTPException(status_code=400, detail="旧密码错误")
    current.hashed_password = hash_password(new)
    db.commit()
    return {"msg": "密码修改成功"}

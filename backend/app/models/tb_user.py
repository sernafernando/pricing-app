from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.core.database import Base


class TBUser(Base):
    """
    Modelo para tb_user - Usuarios del ERP
    Sincronizada desde tbUser (Export 88) via gbp-parser
    
    user_name: Combinación de firstname + lastname o nick
    user_loginname: user_nick del ERP
    user_isactive: Derivado de user_login=1 AND user_Blocked=0
    """
    __tablename__ = "tb_user"

    user_id = Column(Integer, primary_key=True, index=True)
    user_name = Column(String(200))  # firstname + lastname o nick
    user_loginname = Column(String(100), index=True)  # user_nick
    user_email = Column(String(200))
    user_isactive = Column(Boolean, index=True, default=True)
    user_lastupdate = Column(DateTime)
    
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    def __repr__(self):
        return f"<TBUser(user_id={self.user_id}, user_loginname='{self.user_loginname}', user_name='{self.user_name}')>"

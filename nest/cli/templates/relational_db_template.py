from abc import ABC

from nest import __version__ as version
from nest.cli.templates.abstract_base_template import AbstractBaseTemplate


class RelationalDBTemplate(AbstractBaseTemplate, ABC):
    def __init__(self, name, db_type):
        super().__init__(name, db_type)

    def generate_service_file(self) -> str:
        return f"""from src.{self.name}.{self.name}_model import {self.capitalized_name}
from src.{self.name}.{self.name}_entity import {self.capitalized_name} as {self.capitalized_name}Entity
from orm_config import config
from nest.core.decorators import db_request_handler
from functools import lru_cache


@lru_cache()
class {self.capitalized_name}Service:

    def __init__(self):
        self.orm_config = config
        self.session = self.orm_config.get_db()

    @db_request_handler
    def add_{self.name}(self, {self.name}: {self.capitalized_name}):
        new_{self.name} = {self.capitalized_name}Entity(
            **{self.name}.dict()
        )
        self.session.add(new_{self.name})
        self.session.commit()
        return new_{self.name}.id

    @db_request_handler
    def get_{self.name}(self):
        return self.session.query({self.capitalized_name}Entity).all()
        
    @db_request_handler
    def delete_{self.name}(self, {self.name}_id: int):
        self.session.query({self.capitalized_name}Entity).filter_by(id={self.name}_id).delete()
        self.session.commit()
        return {self.name}_id
    
    @db_request_handler
    def update_{self.name}(self, {self.name}_id: int, {self.name}: {self.capitalized_name}):
        self.session.query({self.capitalized_name}Entity).filter_by(id={self.name}_id).update(
            {self.name}.dict()
        )
        self.session.commit()
        return {self.name}_id
         """

    def generate_entity_file(self) -> str:
        return f"""from orm_config import config
from sqlalchemy import Column, Integer, String, Float


class {self.capitalized_name}(config.Base):
    __tablename__ = "{self.name}"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)
        """

    def generate_requirements_file(self) -> str:
        return f"""anyio==4.12.1
click==8.1.8
fastapi==0.136.3
fastapi-utils==0.8.0
greenlet==3.2.4
h11==0.16.0
idna==3.11
pydantic==2.12.4
python-dotenv==1.2.1
sniffio==1.3.1
SQLAlchemy==2.0.44
starlette==1.1.0
typing_extensions==4.15.0
uvicorn==0.38.0
pynest-api=={version}
    """

    def generate_dockerfile(self) -> str:
        pass

    def generate_orm_config_file(self) -> str:
        base_template = f"""from nest.core.database.base_orm import OrmService
import os
from dotenv import load_dotenv

load_dotenv()


        """

        if self.db_type == "sqlite":
            return f"""{base_template}
    config = OrmService(
        db_type="{self.db_type}",
        config_params=dict(
            db_name=os.getenv("SQLITE_DB_NAME", "{self.name}_db"),
        )
    )
            """
        else:
            return f"""{base_template}
    config = OrmService(
        db_type="{self.db_type}",
        config_params=dict(
            host=os.getenv("{self.db_type.upper()}_HOST"),
            db_name=os.getenv("{self.db_type.upper()}_DB_NAME"),
            user=os.getenv("{self.db_type.upper()}_USER"),
            password=os.getenv("{self.db_type.upper()}_PASSWORD"),
            port=int(os.getenv("{self.db_type.upper()}_PORT")),
        )
    )
                    """


if __name__ == "__main__":
    relational_db_template = RelationalDBTemplate("users", "mysql")
    print(relational_db_template.generate_orm_config_file())

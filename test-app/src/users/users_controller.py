from nest.core import Controller, Delete, Get, HttpCode, Post
from nest.common.decorators import Body, Param, Query
from nest.common.exceptions import NotFoundException

from src.users.users_model import CreateUserDto, UserResponse
from src.users.users_service import UsersService


@Controller("/users", tag="users")
class UsersController:
    def __init__(self, users_service: UsersService) -> None:
        self.users_service = users_service

    @Get("/")
    def get_all(
        self,
        limit: int = Query("limit", default=10),
    ) -> list[UserResponse]:
        users = self.users_service.find_all()
        return users[:limit]

    @Post("/")
    @HttpCode(201)
    def create(
        self,
        body: CreateUserDto = Body(),
    ) -> UserResponse:
        return self.users_service.create(body)

    @Get("/{user_id}")
    def get_one(
        self,
        user_id: int = Param("user_id"),
    ) -> UserResponse:
        user = self.users_service.find_one(user_id)
        if user is None:
            raise NotFoundException(f"User {user_id} not found")
        return user

    @Delete("/{user_id}")
    def delete(
        self,
        user_id: int = Param("user_id"),
    ) -> dict:
        if not self.users_service.delete(user_id):
            raise NotFoundException(f"User {user_id} not found")
        return {"deleted": user_id}

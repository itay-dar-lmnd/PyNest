from __future__ import annotations

from nest.core import Injectable

from src.users.users_model import CreateUserDto, UserResponse


@Injectable
class UsersService:
    def __init__(self) -> None:
        self._db: dict[int, UserResponse] = {}
        self._next_id = 1

    def create(self, dto: CreateUserDto) -> UserResponse:
        user = UserResponse(id=self._next_id, name=dto.name, email=dto.email)
        self._db[self._next_id] = user
        self._next_id += 1
        return user

    def find_all(self) -> list[UserResponse]:
        return list(self._db.values())

    def find_one(self, user_id: int) -> UserResponse | None:
        return self._db.get(user_id)

    def delete(self, user_id: int) -> bool:
        return self._db.pop(user_id, None) is not None

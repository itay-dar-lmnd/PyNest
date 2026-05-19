from __future__ import annotations

from nest.core import Controller, Get, Post
from nest.core.decorators.guards import UseGuards
from nest.common.decorators import Body, Headers

from src.auth.auth_guards import AdminGuard, BearerGuard
from src.auth.auth_service import AuthService
from src.auth.token_store import TokenStore


@Controller("/auth", tag="auth")
class AuthController:
    def __init__(
        self,
        auth_service: AuthService,
        token_store: TokenStore,
    ) -> None:
        self.auth_service = auth_service
        self.token_store = token_store

    @Get("/check")
    def check_token(
        self,
        authorization: str = Headers("authorization", default=""),
    ) -> dict:
        token = authorization.replace("Bearer ", "")
        return self.auth_service.validate_and_get_products(token)

    @Get("/protected")
    @UseGuards(BearerGuard)
    def protected(
        self,
        authorization: str = Headers("authorization", default=""),
    ) -> dict:
        token = authorization.replace("Bearer ", "")
        return {"message": "Access granted", "is_admin": self.token_store.is_admin(token)}

    @Get("/admin-only")
    @UseGuards(BearerGuard, AdminGuard)
    def admin_only(self) -> dict:
        return {"message": "Admin access confirmed"}

    @Post("/tokens")
    @UseGuards(AdminGuard)
    def add_token(
        self,
        body: dict = Body(),
    ) -> dict:
        token = body.get("token", "")
        if not token:
            from nest.common.exceptions import BadRequestException
            raise BadRequestException("token field required")
        self.token_store.add_token(token)
        return {"added": token}

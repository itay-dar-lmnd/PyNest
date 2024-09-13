from abc import ABC, abstractmethod
from typing import Type, TypeVar

from litestar import Litestar

# from nest.core.pynest_application import PyNestApp
from nest.core.pynest_container import PyNestContainer


class LitestarFactory(AbstractPyNestFactory):
    """Factory class for creating PyNest applications."""

    @staticmethod
    def create(main_module: Type[ModuleType], **kwargs):
        """
        Create a PyNest application with the specified main module class.

        Args:
            main_module (ModuleType): The main module for the PyNest application.
            **kwargs: Additional keyword arguments for the FastAPI server.

        Returns:
            PyNestApp: The created PyNest application.
        """
        container = PyNestContainer()
        container.add_module(main_module)
        http_server = PyNestFactory._create_server(**kwargs)
        return PyNestApp(container, http_server)

    @staticmethod
    def _create_server(**kwargs) -> FastAPI:
        """
        Create a FastAPI server.

        Args:
            **kwargs: Additional keyword arguments for the FastAPI server.

        Returns:
            FastAPI: The created FastAPI server.
        """
        return Litestar(**kwargs)
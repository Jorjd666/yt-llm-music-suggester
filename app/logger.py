
from loguru import logger
import sys

# Configure logger once at import
logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

__all__ = ["logger"]

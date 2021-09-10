import sys
import logging
from logging.handlers import RotatingFileHandler

FORMATTER = logging.Formatter(fmt="[%(asctime)s] %(levelname)-8s %(name)-6s %(message)s", datefmt="%H:%M:%S %d-%m-%Y")
LOG_FILE = "log"
LOG_FILE_SIZE = 10 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 5


def _get_console_handler():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(FORMATTER)
    return console_handler


def _get_file_handler():
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_FILE_SIZE, backupCount=LOG_FILE_BACKUP_COUNT)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(FORMATTER)
    return file_handler


def get_logger(logger_name):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.addHandler(_get_console_handler())
    logger.addHandler(_get_file_handler())
    logger.propagate = False
    return logger


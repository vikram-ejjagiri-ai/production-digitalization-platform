import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)-18s | %(levelname)-7s | %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger(name)

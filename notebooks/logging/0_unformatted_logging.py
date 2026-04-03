import logging

# see the logs which are equal to or at a greater level than WARNING
logging.basicConfig(level=logging.WARNING)

logging.debug("debug")
logging.info("info")
# we are mostly interested in the following logs in production
logging.warning("warning")
logging.error("error")
logging.critical("critical")


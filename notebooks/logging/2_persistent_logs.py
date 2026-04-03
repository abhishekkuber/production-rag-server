import logging


console_handler = logging.StreamHandler()
file_handler = logging.FileHandler('app.log')

# https://docs.python.org/3/library/logging.html#logrecord-attributes
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s", handlers=[file_handler, console_handler])

logging.debug("debug")
logging.info("info")
# we are mostly interested in the following logs in production
logging.warning("warning")
logging.error("error")
logging.critical("critical")

'''
2026-03-30 12:51:50,741 - DEBUG - debug
2026-03-30 12:51:50,741 - INFO - info
2026-03-30 12:51:50,741 - WARNING - warning
2026-03-30 12:51:50,741 - ERROR - error
2026-03-30 12:51:50,741 - CRITICAL - critical
'''
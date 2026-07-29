import os
import logging
import contextvars

# Context variable to track the current wiki ID in async/thread context
current_wiki_id = contextvars.ContextVar("current_wiki_id", default=None)

class WikiLogHandler(logging.Handler):
    def emit(self, record):
        wiki_id = current_wiki_id.get()
        if wiki_id is not None:
            log_dir = "/app/data/logs"
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{wiki_id}.log")
            try:
                msg = self.format(record)
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

def setup_logging():
    log_dir = "/app/data/logs"
    os.makedirs(log_dir, exist_ok=True)
    global_log_path = os.path.join(log_dir, "global.log")

    # Format
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Stream Handler (Stdout)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # Global File Handler
    global_file_handler = logging.FileHandler(global_log_path, encoding="utf-8")
    global_file_handler.setFormatter(formatter)

    # Wiki Log Handler
    wiki_log_handler = WikiLogHandler()
    wiki_log_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Suppress third-party verbosity to keep cruft out of the logs
    logging.getLogger("mwclient").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(global_file_handler)
    root_logger.addHandler(wiki_log_handler)

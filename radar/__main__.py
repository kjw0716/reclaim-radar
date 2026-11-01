import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
import uvicorn
from .config import DATA
from .app import create_app

def main():
    DATA.mkdir(parents=True,exist_ok=True)
    lock=open(DATA/"server.lock","a+b")
    try:
        if os.name=="nt":
            import msvcrt
            lock.seek(0);lock.write(b"0");lock.flush();lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        print("回收雷达已运行，拒绝重复启动。",flush=True);return 2
    logs=DATA/"logs";logs.mkdir(exist_ok=True)
    handler=RotatingFileHandler(logs/"radar.log",maxBytes=3_000_000,backupCount=5,encoding="utf-8")
    logging.basicConfig(level=logging.INFO,handlers=[handler,logging.StreamHandler()],format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app=create_app()
    (DATA/"runtime.json").write_text(json.dumps({"pid":os.getpid(),"app":"reclaim-radar","executable":sys.executable}),encoding="utf-8")
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=8765,log_level="info",workers=1))
    def stop_when_requested():
        app.state.shutdown.wait();server.should_exit=True
    threading.Thread(target=stop_when_requested,daemon=True).start()
    try:server.run()
    finally:
        (DATA/"runtime.json").unlink(missing_ok=True)
        lock.close()
    return 0

if __name__=="__main__":sys.exit(main())

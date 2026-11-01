"""Offline restore, schema/integrity validation, lock enforcement and pre-restore snapshot."""
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from .config import DATA
from .db import Database

def restore(source):
    source=Path(source).resolve(strict=True)
    DATA.mkdir(exist_ok=True)
    target=(DATA/"radar.sqlite3").resolve()
    if source==target:raise ValueError("备份不能是活动数据库本身")
    lock=open(DATA/"server.lock","a+b")
    try:
        if os.name=="nt":
            import msvcrt
            lock.seek(0);lock.write(b"0");lock.flush();lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise ValueError("请先停止回收雷达再恢复")
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)) as c:
            if c.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("备份完整性检查失败")
            tables={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"listings","settings","references_prices","audit"}<=tables:raise ValueError("不是回收雷达备份")
        if target.exists():Database(DATA).backup()
        temporary=DATA/"restore.tmp"
        shutil.copyfile(source,temporary)
        # Only these resolved exact files in DATA are removed after successful validation.
        for suffix in ("-wal","-shm"):
            journal=Path(str(target)+suffix)
            if journal.parent!=DATA.resolve():raise ValueError("日志路径超出数据目录")
            journal.unlink(missing_ok=True)
        os.replace(temporary,target)
        print("备份已恢复，原数据库已先备份。")
    finally:lock.close()

if __name__=="__main__":
    try:restore(sys.argv[1])
    except Exception as e:print(str(e));sys.exit(1)

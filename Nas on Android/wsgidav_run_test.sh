#!/data/data/com.termux/files/usr/bin/bash
set -e
cd /data/data/com.termux/files/home
./../usr/bin/python3 -m wsgidav.server.server_cli --host=127.0.0.1 --port=8091 --root=/data/data/com.termux/files/home/cellhasher-nas/data/storage --auth=anonymous > /data/data/com.termux/files/home/wsgidav_test.log 2>&1 &
echo $! > /data/data/com.termux/files/home/wsgidav_test.pid
sleep 4
cat /data/data/com.termux/files/home/wsgidav_test.log

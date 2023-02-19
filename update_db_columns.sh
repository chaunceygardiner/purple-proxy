#!/bin/sh

echo "ALTER TABLE Reading ADD COLUMN current_temp_f_680     INTEGER" | sudo sqlite3 /home/purpleproxy/archive/purpleproxy.sdb
echo "ALTER TABLE Reading ADD COLUMN current_humidity_680   INTEGER" | sudo sqlite3 /home/purpleproxy/archive/purpleproxy.sdb
echo "ALTER TABLE Reading ADD COLUMN current_dewpoint_f_680 INTEGER" | sudo sqlite3 /home/purpleproxy/archive/purpleproxy.sdb
echo "ALTER TABLE Reading ADD COLUMN pressure_680           REAL   " | sudo sqlite3 /home/purpleproxy/archive/purpleproxy.sdb
echo "Note: If you're already running version 2.0 or 2.1, you'll see a duplicate column name error for the gas_680 column. That's OK!"
echo "ALTER TABLE Reading ADD COLUMN gas_680                REAL   " | sudo sqlite3 /home/purpleproxy/archive/purpleproxy.sdb

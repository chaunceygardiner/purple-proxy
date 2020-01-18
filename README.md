# purple-proxy
Proxy server for PurpleAir air quality sensor.  Serves current and archived readings which are averaged over a specified interval.

Instructions:

1. Link or copy all files under the etc directory to their corresponding places under /etc.

2. mkdir -p /home/purpleproxy/bin

3. mkdir /home/purpleproxy/archive

4. Add a purpleproxy.conf file under in the /home/purplerpoxy directory with the following contents:

`# PurpleProxy configuration file

debug                 = 0
log-to-stdout         = 0

service-name          = purple-proxy

hostname              = purple-air.foobar.com
port                  = 80
timeout-secs          = 15

request-server-port   = 8000

poll-freq-secs        = 30
archive-interval-secs = 300

database-file         = /home/purpleproxy/archive/purpleproxy.sdb`

5. service rsyslog restart

6. service logrotate restart

7. systemctl enable purple-proxy

8. service purple-proxy start


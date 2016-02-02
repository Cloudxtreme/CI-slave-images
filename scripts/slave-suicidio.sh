
#!/bin/bash

# slave-suicidio
# 
# A script to shutdown any disconnected Jenkins slaves
# 
# The script will check for an active communication channel 
# between itself and the jenkins master.
# 
# 
# The test for the communication channel is -
#   1. is Java running?
#   2. thats it!
# 
# If successful the script will shut the machine down 

readonly SCRIPT_NAME=$(basename $0)

# grace period to wait before the initial check
# this defaults to 59 minutes as AWS charges by 
# the hour rounded up to the nearest hour
readonly GRACE_PERIOD_SECONDS=59*60

# period in which to check after initial grace period
# this defaults to 60 minutes
readonly CHECK_PERIOD_SECONDS=60*60

# process to check for 
readonly PROCESS_NAME="java"

log() {
  echo "$@"
  logger -p user.notice -t $SCRIPT_NAME "$@"
}

# sleep for our intial period
sleep $GRACE_PERIOD_SECONDS

while true 
do
    
    if pgrep $PROCESS_NAME > /dev/null 
    then
        log "${PROCESS_NAME} is still running"
    else
        log "${PROCESS_NAME} is not running - shutting down..."
        /sbin/shutdown -h now
        log "bye..."
    fi

    sleep $CHECK_PERIOD_SECONDS
done
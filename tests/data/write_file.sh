#!/bin/sh

FILE=$1
COUNT=0
while [ 1 ] ; do
    echo $COUNT >> $FILE
    date >> $FILE
    COUNT=`expr $COUNT + 1`
    sleep .001
done

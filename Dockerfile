FROM ubuntu:16.04

RUN apt-get update
RUN apt-get -y install python3 python3-dev python3-pip git

WORKDIR /data
COPY ./requirements* /data/
COPY setup.py /data/
COPY setup.cfg /data/
COPY scriptworker/ /data/scriptworker
COPY .git /data/.git
COPY .coveragerc /data/
COPY tox.ini /data/
COPY MANIFEST.in /data/
COPY environment.yml /data/
#COPY scriptworker.yaml /data/
COPY version.json /data/
COPY secrets.json /data/
# COPY * /data/
RUN ls -al /data/

RUN pip3 install -r requirements-dev.txt
RUN pip3 install -r requirements-test-dev.txt
RUN python3 setup.py develop

#ENTRYPOINT ["/bin/bash"]

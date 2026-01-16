FROM python:3.11-slim-bookworm

ENV USERNAME app
ENV UID 1001
ENV USERHOME /app
ENV APP_ROOT ${USERHOME}/src

RUN apt-get update \
    && apt-get -y upgrade

RUN mkdir -p ${APP_ROOT}

COPY main.py ${APP_ROOT}/
COPY start.sh ${APP_ROOT}/
COPY requirements.txt ${APP_ROOT}/

RUN pip install -r ${APP_ROOT}/requirements.txt \
    && chmod 0755 ${APP_ROOT}/*.sh

RUN addgroup ${USERNAME} --gid ${UID} \
    && adduser  ${USERNAME} --uid ${UID} --gid ${UID} --home ${USERHOME} --shell /bin/bash --no-create-home \
    && chown -R ${USERNAME}:${USERNAME} ${USERHOME}

# TZ
ENV TZ=Europe/Berlin
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Clean
RUN rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /var/cache/apt/archives/*

USER ${USERNAME}:${USERNAME}
WORKDIR ${APP_ROOT}

CMD ["./start.sh"]

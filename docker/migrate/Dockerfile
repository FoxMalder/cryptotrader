FROM debian

ENV VERSION v3.0.1
ENV PLATFORM linux-amd64
ENV FILE_NAME migrate.$PLATFORM

ENV SOURCE https://github.com/mattes/migrate/releases/download/$VERSION/$FILE_NAME.tar.gz

RUN apt-get update && \
    apt-get install -y curl && \
    curl -L $SOURCE | tar xvz && \
    ln -s /$FILE_NAME /usr/bin/migrate && \
    chmod +x /usr/bin/migrate

COPY docker/migrate/entrypoint.sh /usr/local/bin/

ENTRYPOINT ["entrypoint.sh"]
CMD migrate --help

FROM python

RUN pip install mypy
WORKDIR /usr/src
COPY ./mypy.ini /usr/src/mypy.ini

CMD mypy --config-file mypy.ini .

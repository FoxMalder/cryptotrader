FROM python

RUN mkdir /etc/cryptotrader
COPY . /usr/src
WORKDIR /usr/src
RUN pip install -r requirements.txt

CMD python -m cryptotrader --config test.yaml execute

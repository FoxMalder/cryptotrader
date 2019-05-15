FROM coala/base

# Install project's dependencies to correct isort's work.
COPY requirements.txt .
COPY panel/requirements.txt ./requirements-panel.txt
RUN	pip install -r requirements.txt && \
	pip install -r requirements-panel.txt

# Install coala in virtualenv to isolate its dependencies.
RUN pip install virtualenv \
	&& virtualenv --system-site-packages /coala_env \
	&& source /coala_env/bin/activate \
	&& pip install -I coala-bears

CMD source /coala_env/bin/activate \
    && coala \
    && rm -f `find . -name *.orig`
